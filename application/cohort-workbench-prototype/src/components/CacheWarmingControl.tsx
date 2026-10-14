import { useEffect, useState } from 'react'
import type { CacheWarmingStatus, LibraryDataSource } from '../data/LibraryDataSource'
import { InfoTip } from './Common'

export function CacheWarmingControl({ dataSource }: { dataSource: LibraryDataSource }) {
  const [status, setStatus] = useState<CacheWarmingStatus | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    let disposed = false
    let timer: ReturnType<typeof setTimeout>
    async function poll() {
      try {
        const next = await dataSource.loadCacheWarmingStatus?.()
        if (!disposed && next) {
          setStatus(next)
          timer = setTimeout(() => void poll(), 3000)
        }
      } catch {
        // Older services do not expose this optional control.
      }
    }
    void poll()
    return () => { disposed = true; clearTimeout(timer) }
  }, [dataSource])
  async function toggle() {
    if (!status || !dataSource.setCacheWarmingEnabled) return
    setBusy(true)
    setError('')
    try { setStatus(await dataSource.setCacheWarmingEnabled(!status.enabled)) }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { setBusy(false) }
  }
  if (!status) return null
  return <div className="cache-warming-control">
    <span className="inline-heading">Cache warming: {status.state}<InfoTip text="Builds activity indexes, saved scenario evaluations and standard previews while the service is idle. User requests take priority after the current build finishes. Pause applies to this service session; warming stays off in read-only mode." /></span>
    {!status.read_only && <button className="secondary-action compact" type="button" disabled={busy} onClick={() => void toggle()}>{status.enabled ? 'Pause' : 'Enable'}</button>}
    {error && <span role="alert">{error}</span>}
  </div>
}
