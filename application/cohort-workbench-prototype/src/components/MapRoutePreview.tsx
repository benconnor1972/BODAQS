import { useEffect, useRef } from 'react'
import { Map as MapIcon } from 'lucide-react'
import maplibregl, {
  type GeoJSONSource,
  type Map as MapLibreMap,
  type StyleSpecification,
} from 'maplibre-gl'
import type { Feature, FeatureCollection, LineString, Point } from 'geojson'
import type { SessionRecord, TrackRecord } from '../domain/types'

type LineProperties = {
  color: string
  width: number
  opacity: number
}

type PointProperties = {
  color: string
  label: string
  radius: number
}

type SessionPathOverlay = {
  id: string
  label: string
  path: Array<[number, number]>
}

export type HighlightPathOverlay = {
  id: string
  label: string
  path: Array<[number, number]>
  color?: string
  width?: number
  opacity?: number
}

const SESSION_COLOR = '#101820'
const STUDY_SESSION_COLOR = '#315a6d'
const SELECTED_TRACK_COLOR = '#008c95'
const STUDY_TRACK_COLOR = '#b66a2c'

const LINE_SOURCE_ID = 'bodaqs-route-lines'
const LINE_LAYER_ID = 'bodaqs-route-lines'

const OSM_RASTER_STYLE: StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: 'raster',
      tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
      tileSize: 256,
      attribution: '(c) OpenStreetMap contributors',
    },
  },
  layers: [
    {
      id: 'osm',
      type: 'raster',
      source: 'osm',
    },
  ],
}

export function MapRoutePreview({
  primarySession,
  primaryGpsPath,
  sessionPaths = [],
  highlightPaths = [],
  selectedTracks,
  currentTracks,
}: {
  primarySession: SessionRecord | null
  primaryGpsPath?: Array<[number, number]>
  sessionPaths?: SessionPathOverlay[]
  highlightPaths?: HighlightPathOverlay[]
  selectedTracks: TrackRecord[]
  currentTracks: TrackRecord[]
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<MapLibreMap | null>(null)
  const markerRef = useRef<maplibregl.Marker[]>([])
  const visiblePoints = collectVisiblePositions(primarySession, primaryGpsPath, sessionPaths, highlightPaths, selectedTracks, currentTracks)
  const hasVisiblePoints = visiblePoints.length > 0

  useEffect(() => {
    if (!hasVisiblePoints || !containerRef.current || mapRef.current) {
      return
    }

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: OSM_RASTER_STYLE,
      center: [0, 0],
      zoom: 13,
      attributionControl: false,
    })
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')
    map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right')
    mapRef.current = map

    return () => {
      clearMarkers(markerRef.current)
      markerRef.current = []
      map.remove()
      mapRef.current = null
    }
  }, [hasVisiblePoints])

  useEffect(() => {
    if (!containerRef.current) {
      return
    }

    const observer = new ResizeObserver(() => {
      mapRef.current?.resize()
    })
    observer.observe(containerRef.current)
    return () => {
      observer.disconnect()
    }
  }, [])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !hasVisiblePoints) {
      return
    }
    const activeMap = map

    function applyOverlayData() {
      const overlayData = buildOverlayData(primarySession, primaryGpsPath, sessionPaths, highlightPaths, selectedTracks, currentTracks)
      ensureOverlayLayers(activeMap, overlayData.lines)
      markerRef.current = syncPointMarkers(activeMap, markerRef.current, overlayData.points.features)
      fitMapToPoints(activeMap, overlayData.boundsPoints)
    }

    if (activeMap.isStyleLoaded()) {
      applyOverlayData()
      return
    }

    activeMap.once('load', applyOverlayData)
    return () => {
      activeMap.off('load', applyOverlayData)
    }
  }, [currentTracks, hasVisiblePoints, highlightPaths, primaryGpsPath, primarySession, selectedTracks, sessionPaths])

  if (!hasVisiblePoints) {
    return (
      <div className="map-empty">
        <MapIcon size={24} />
        <span>Select a session or track to preview GPS context.</span>
      </div>
    )
  }

  return <div className="map-route-preview" ref={containerRef} role="img" aria-label="GPS route map preview" />
}

function collectVisiblePositions(
  primarySession: SessionRecord | null,
  primaryGpsPath: Array<[number, number]> | undefined,
  sessionPaths: SessionPathOverlay[],
  highlightPaths: HighlightPathOverlay[],
  selectedTracks: TrackRecord[],
  currentTracks: TrackRecord[],
) {
  const primaryPoints = primaryGpsPath ?? primarySession?.gps ?? []
  return [
    ...primaryPoints,
    ...sessionPaths.flatMap((sessionPath) => sessionPath.path),
    ...highlightPaths.flatMap((highlightPath) => highlightPath.path),
    ...selectedTracks.flatMap((track) => track.points),
    ...selectedTracks.flatMap((track) => track.trackpoints.map((trackpoint) => trackpoint.position)),
    ...currentTracks.flatMap((track) => track.points),
    ...currentTracks.flatMap((track) => track.trackpoints.map((trackpoint) => trackpoint.position)),
  ].filter(isValidPosition)
}

function buildOverlayData(
  primarySession: SessionRecord | null,
  primaryGpsPath: Array<[number, number]> | undefined,
  sessionPaths: SessionPathOverlay[],
  highlightPaths: HighlightPathOverlay[],
  selectedTracks: TrackRecord[],
  currentTracks: TrackRecord[],
) {
  const primaryPoints = filterPositions(primaryGpsPath ?? primarySession?.gps ?? [])
  const lineFeatures: Array<Feature<LineString, LineProperties>> = []
  const pointFeatures: Array<Feature<Point, PointProperties>> = []
  const boundsPoints: Array<[number, number]> = []

  if (primarySession && primaryPoints.length >= 2) {
    lineFeatures.push(routeLineFeature('primary-session', primaryPoints, SESSION_COLOR, 4, 0.9))
    addEndpointMarkers(pointFeatures, primaryPoints, SESSION_COLOR, 'Session')
    boundsPoints.push(...primaryPoints)
  }

  sessionPaths.forEach((sessionPath, index) => {
    const points = filterPositions(sessionPath.path)
    if (points.length >= 2) {
      lineFeatures.push(routeLineFeature(`study-session-${sessionPath.id}`, points, STUDY_SESSION_COLOR, 3, 0.54))
      if (index === 0) {
        addEndpointMarkers(pointFeatures, points, STUDY_SESSION_COLOR, 'Study Set')
      }
      boundsPoints.push(...points)
    }
  })

  highlightPaths.forEach((highlightPath) => {
    const points = filterPositions(highlightPath.path)
    if (points.length >= 2) {
      lineFeatures.push(
        routeLineFeature(
          `highlight-${highlightPath.id}`,
          points,
          highlightPath.color ?? SELECTED_TRACK_COLOR,
          highlightPath.width ?? 6,
          highlightPath.opacity ?? 0.95,
        ),
      )
      boundsPoints.push(...points)
    }
  })

  selectedTracks.forEach((track) => {
    const points = filterPositions(track.points)
    if (points.length >= 2) {
      lineFeatures.push(routeLineFeature(`selected-track-${track.id}`, points, SELECTED_TRACK_COLOR, 3, 0.95))
      boundsPoints.push(...points)
    }
    addTrackpointMarkers(pointFeatures, track, SELECTED_TRACK_COLOR)
  })

  currentTracks.forEach((track) => {
    const points = filterPositions(track.points)
    if (points.length >= 2) {
      lineFeatures.push(routeLineFeature(`study-track-${track.id}`, points, STUDY_TRACK_COLOR, 2, 0.86))
      boundsPoints.push(...points)
    }
    addTrackpointMarkers(pointFeatures, track, STUDY_TRACK_COLOR)
  })

  pointFeatures.forEach((feature) => {
    boundsPoints.push(feature.geometry.coordinates as [number, number])
  })

  return {
    lines: {
      type: 'FeatureCollection',
      features: lineFeatures,
    } satisfies FeatureCollection<LineString, LineProperties>,
    points: {
      type: 'FeatureCollection',
      features: pointFeatures,
    } satisfies FeatureCollection<Point, PointProperties>,
    boundsPoints,
  }
}

function routeLineFeature(
  id: string,
  points: Array<[number, number]>,
  color: string,
  width: number,
  opacity: number,
): Feature<LineString, LineProperties> {
  return {
    type: 'Feature',
    id,
    properties: { color, width, opacity },
    geometry: {
      type: 'LineString',
      coordinates: points,
    },
  }
}

function addEndpointMarkers(
  features: Array<Feature<Point, PointProperties>>,
  points: Array<[number, number]>,
  color: string,
  labelPrefix: string,
) {
  if (points.length === 0) {
    return
  }
  features.push(pointFeature(`${labelPrefix} start`, points[0], color, 6))
  features.push(pointFeature(`${labelPrefix} end`, points[points.length - 1], color, 5))
}

function addTrackpointMarkers(
  features: Array<Feature<Point, PointProperties>>,
  track: TrackRecord,
  color: string,
) {
  track.trackpoints.forEach((trackpoint, index) => {
    if (!isValidPosition(trackpoint.position)) {
      return
    }
    features.push(pointFeature(String(index + 1), trackpoint.position, color, 6))
  })
}

function pointFeature(
  label: string,
  coordinates: [number, number],
  color: string,
  radius: number,
): Feature<Point, PointProperties> {
  return {
    type: 'Feature',
    properties: { color, label, radius },
    geometry: {
      type: 'Point',
      coordinates,
    },
  }
}

function ensureOverlayLayers(
  map: MapLibreMap,
  lineData: FeatureCollection<LineString, LineProperties>,
) {
  const lineSource = map.getSource(LINE_SOURCE_ID) as GeoJSONSource | undefined
  if (lineSource) {
    lineSource.setData(lineData)
  } else {
    map.addSource(LINE_SOURCE_ID, { type: 'geojson', data: lineData })
    map.addLayer({
      id: LINE_LAYER_ID,
      type: 'line',
      source: LINE_SOURCE_ID,
      layout: {
        'line-cap': 'round',
        'line-join': 'round',
      },
      paint: {
        'line-color': ['get', 'color'],
        'line-width': ['get', 'width'],
        'line-opacity': ['get', 'opacity'],
      },
    })
  }
}

function syncPointMarkers(
  map: MapLibreMap,
  currentMarkers: maplibregl.Marker[],
  features: Array<Feature<Point, PointProperties>>,
) {
  clearMarkers(currentMarkers)
  return features.map((feature) => {
    const element = document.createElement('div')
    element.className = 'map-route-marker'
    element.style.setProperty('--marker-color', feature.properties.color)
    element.style.setProperty('--marker-radius', `${feature.properties.radius}px`)
    element.textContent = feature.properties.label
    return new maplibregl.Marker({ element, anchor: 'bottom' })
      .setLngLat(feature.geometry.coordinates as [number, number])
      .addTo(map)
  })
}

function clearMarkers(markers: maplibregl.Marker[]) {
  markers.forEach((marker) => marker.remove())
}

function fitMapToPoints(map: MapLibreMap, points: Array<[number, number]>) {
  const validPoints = filterPositions(points)
  if (validPoints.length === 0) {
    return
  }
  if (validPoints.length === 1) {
    map.easeTo({ center: validPoints[0], zoom: 15, duration: 450 })
    return
  }

  const bounds = new maplibregl.LngLatBounds(validPoints[0], validPoints[0])
  validPoints.slice(1).forEach((point) => bounds.extend(point))
  map.fitBounds(bounds, { padding: 36, maxZoom: 16, duration: 450 })
}

function filterPositions(points: Array<[number, number]>) {
  return points.filter(isValidPosition)
}

function isValidPosition(point: [number, number]) {
  const [longitude, latitude] = point
  return (
    Number.isFinite(longitude) &&
    Number.isFinite(latitude) &&
    longitude >= -180 &&
    longitude <= 180 &&
    latitude >= -90 &&
    latitude <= 90
  )
}
