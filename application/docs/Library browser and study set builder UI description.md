# UI description: Library Browser and Study Set Builder
This bit of the UI is intended to allow users to set the scope for analysis by defining a ‘study set’ (previously called a ‘cohort’). A study set specifies one or more sessions, 0 or more ‘groupings’ (previously called ‘aggregations’ – sets of one or more of the sessions in the study set) and 0 or more ‘tracks’ (collections of geospatial locations).

The handoff to visualization is a single study set definition.

## Overall layout
The UI is comprised of two panels with a fixed left-right orientation. The left panel is the ‘library browser’; the right is the ‘study set builder’. Both panels should be collapsible horizontally for when screen real estate is scarce.

## Library Browser
The Library Browser is intended to do three things:
-	allow users to find and specify sessions they want to place in a cohort
-	allow users to attach tracks to a study set (including defining new tracks)
-	provide a shortcut to analysis with a degenerate study set(i.e. pick a single session and go directly to analysis, with a one-session, 0 grouping, 0 geopoint study set created invisibly).
First implementation could be just the library selector and session selector.

It comprises the following UI elements:

### Library Selector
Permits the user to select one or more libraries from the library root. All the sessions in selected libraries are then available, subject to further filtering

### Session Selector
The UI point where sessions are added to a study set. Features of this element are:
-	Column control. The user can add, remove, resize and reorder the displayed columns. Available columns are a defined subset of run, session, preprocessing and bike metadata.
-	Ad-hoc filtering and sorting. The user can sort and filter on any of the available columns.
-	Quick metadata access. The user can click icons to view session notes, session metadata and data quality warnings.
-	Multi-select. The user can select one or more rows from the table. One of these rows is the primary selection, which determines the data displayed in the GPS Location UI element.
-	‘Add to study set’ control. The user can add one or more selected sessions to the current study set.
-	‘Analyze now’ control. The user can go directly to analysis with a single session.

### Filter Manager
A UI element that lists available filters, allows filters to be toggled on and off, and allows creation of new filters. Unlike ad-hoc filtering on the session selector columns, this control allows filters to be re-used. It is intended that multiple filters can be applied at one time.

### GPS Location window
A UI element that shows GPS data for the primary selection and/or selected Tracks. Also includes an entry point for creation of new Tracks.

### Track Manager
The UI point where Tracks are added to the study set or selected for display in the GPS location window. Also allows creation, editing and deletion of Tracks.

## Study Set Builder
The study set builder is intended to provide viewing (and editing) of the content of the current Study Set; permit saving, loading and editing of persisted Study Sets; and provide the main entry point for analysis.
It has two UI elements: Current Study Set and Saved Study Sets.

### Current Study Set
This set of controls contains two tables, one each for the Study Set’s Sessions and Tracks. It also allows groupings to be specified by selection of multiple sessions from the Sessions Table.

The Sessions Table displays the same set of columns as the Sessions Selector in the Library Browser, with a control for each to remove the session from the Study Set (and any groupings it is a part of). The Sessions Table also allows the user to define ‘groupings’.  (Implementation details TBD. Ideally these would be displayed with link lines, but simply having one or more grouping columns with checkboxes would be OK).

The Tracks table lists tracks that form part of the Study Set, with a control to remove each one. The columns show the Track name, the number of points, and controls to access deeper data (coordinates, map, distances etc).
The Current Study Set UI element also contains a text box and save button so the Study Set definition can be persisted, and an ‘analyze’ button to move to analysis of the Current Study Set

### Saved Study Sets
This set of controls contains a table listing saved Study Sets, with controls to analyze, view and load a single Study Set.
