# Find and open an iPhone app by touch

When the user asks to open an app, check the current frame. If the requested app is already open, continue the task. Otherwise return Home once, unless the icon grid is already visible.

1. Inspect the grid and dock for the requested icon and label. If visible, tap its center. Verify the resulting app from its title, navigation, or distinctive content before reporting success.
2. If the icon is absent, drag left across the middle of the grid (roughly x=.80 to .20 at y=.50) to inspect the next page. Send one drag per observation. In the action note record the direction and a couple of recognizable page labels or the active page dot.
3. Compare the settled grid with the previous page using its icons and page dots. If a drag did not move the page, try once across another clear part of the grid. At the App Library or rightmost boundary, drag right through the grid to inspect pages on the other side of the starting page. Pass through previously seen pages as needed. At Today View, drag left to return to the grid. Keep track of the direction already searched.
4. Inspect relevant visible folders or the App Library when the grid search is exhausted. Tap the matching app icon when you can identify it. If all accessible pages have been searched or the phone rejects touch, report what blocked the search. Never launch an app by bundle identifier.
