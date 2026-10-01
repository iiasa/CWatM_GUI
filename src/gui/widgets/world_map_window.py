"""Info ▸ World Map - where CWatM is run, and where its users are.

Two views, one at a time, switched by the two buttons below the map:

- **CWatM runs** (blue): the anonymous run-location counts of the CWatM account
  (``get_run_locations``: lon, lat, number of runs that earned a point - no users,
  no dates);
- **User location** (orange): the own locations of the users who ticked *Show my
  location on the world map* (``get_user_locations``: no names, rounded to 0.5°,
  counted per place).

One circle per place; the more runs (or users) at a place, the larger the circle.
The map shows 80°N - 60°S; its first size fits -180..180° x 90°N..60°S exactly
(Leaflet EPSG:4326 at zoom 1 = 1024 px for 360°, 2.84 px per degree). The window can
be maximised; there is no Close/Refresh button (the title bar closes it).

Built like Show Basin (``basin_viewer2``): folium (Leaflet) page in EPSG:4326, the
**basemap chosen in Preferences ▸ Display ▸ Default openstreet map** as a WMS layer
through the shared ``osmtile://`` scheme handler. folium and the viewer helpers are
imported only when the window opens (fast-startup rule). The data comes through the
main window's ``AccountWorker`` (public functions - no login needed).
"""

import json
import math

from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import (QButtonGroup, QDialog, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout)

from src.gui.utils import theme
from src.gui.utils.gui_log import get_logger

log = get_logger("world_map")

PAGE = "worldmap"            # served at osmtile://worldmap/
LAT_NORTH, LAT_SOUTH = 80, -60
# Map content - the same colours on every theme (like the basin/NetCDF maps).
RUNS_STROKE, RUNS_FILL = "#1f5fbf", "#2c7fff"
USERS_STROKE, USERS_FILL = "#b35900", "#e67e22"
MAX_RADIUS = 40
# Leaflet EPSG:4326 at zoom 1: 360 deg = 1024 px, so 150 deg (90N..60S) = 427 px.
MAP_W, MAP_H = 1024, 427
QWIDGETSIZE_MAX = 16777215      # Qt's constant - not exported by PySide6.QtWidgets

MODES = {
    "runs": {
        "title": "Where CWatM has been run",
        "info": ("{places} place(s), {count} run(s). Each blue circle is a place where "
                 "a CWatM run earned a badge point (its first gauge, ~100 m) - the "
                 "bigger the circle, the more runs. Anonymous: no users, no dates."),
    },
    "users": {
        "title": "Where CWatM users are",
        "info": ("{places} place(s), {count} user(s). Each orange circle is where "
                 "users who chose to show their location are (no names, ~50 km) - the "
                 "bigger the circle, the more users. Show yours: account window ▸ "
                 "Show my location on the world map."),
    },
}


def circle_radius(count):
    """Circle radius in screen pixels for a number of runs / users (pure - tested).

    Grows with the square root, so the circle's AREA is proportional to the count
    and one busy place does not cover the map: 1 -> 7, 4 -> 10, 25 -> 19, 100 -> 34,
    capped at MAX_RADIUS."""
    return min(float(MAX_RADIUS), 4.0 + 3.0 * math.sqrt(max(1, int(count))))


def circle_data(locations, key="runs"):
    """[[lat, lon, radius, count], ...], biggest first - so smaller circles are
    drawn later, on top, and stay visible and hoverable (pure - tested)."""
    rows = []
    for loc in locations:
        try:
            lon, lat, count = float(loc["lon"]), float(loc["lat"]), int(loc[key])
        except (KeyError, TypeError, ValueError):
            continue
        if count > 0 and -180 <= lon <= 180 and -90 <= lat <= 90:
            rows.append([lat, lon, round(circle_radius(count), 1), count])
    rows.sort(key=lambda r: -r[3])
    return rows


def build_world_map_html(runs, users, basemap_layer, mode="runs"):
    """The folium EPSG:4326 world map page with both circle layers; ``mode``
    ('runs' / 'users') is the one shown first - window.setMode() switches."""
    import folium
    from src.gui.widgets.basin_viewer2 import (_inline_remote_assets,
                                               _strip_unused_assets)
    m = folium.Map(location=[10, 0], zoom_start=1, crs="EPSG4326", tiles=None,
                   control_scale=True, zoom_control=True)
    html = _strip_unused_assets(m.get_root().render())
    css = ("<style>html,body{width:100%;height:100%;margin:0;padding:0;}"
           ".folium-map{position:absolute!important;top:0;left:0;"
           "width:100%!important;height:100%!important;}"
           ".leaflet-container{cursor:default!important;background:#dddddd;}"
           "</style>")
    html = html.replace("</head>", css + "</head>", 1) if "</head>" in html \
        else css + html
    html = _inline_remote_assets(html)          # before our own script (see basin2)
    js = r"""
    (function(){
      var MAP=__MAP__;
      var N=__NORTH__, S=__SOUTH__;
      MAP.options.zoomSnap=0.25;
      // only 80N..60S (pannable a little beyond, not further)
      MAP.setMaxBounds([[S-5,-200],[N+5,200]]);
      MAP.options.maxBoundsViscosity=1.0;
      L.tileLayer.wms('osmtile://wms/service',{layers:__LAYER__,format:'image/png',
        version:'1.1.1',transparent:false,maxZoom:19,bounds:[[-90,-180],[90,180]],
        attribution:'(c) OpenStreetMap contributors'}).addTo(MAP).bringToBack();
      // everything beyond 80N / 60S covered in the map background grey (this also
      // hides the black no-data bands the OSM WMS returns near the poles)
      [[[N,-400],[100,400]],[[-100,-400],[S,400]]].forEach(function(b){
        L.rectangle(b,{stroke:false,fillColor:'#dddddd',fillOpacity:1,
                       interactive:false}).addTo(MAP);});
      function layer(data,stroke,fill,one,many){
        var g=L.layerGroup();
        data.forEach(function(d){
          L.circleMarker([d[0],d[1]],{radius:d[2],color:stroke,weight:1,
            fillColor:fill,fillOpacity:0.55})
           .bindTooltip(d[3]+(d[3]==1?one:many)+'<br>'
                        +d[1].toFixed(3)+', '+d[0].toFixed(3))
           .addTo(g);});
        return g;}
      var LAYERS={
        runs: layer(__RUNS__,__RUNS_STROKE__,__RUNS_FILL__,' run',' runs'),
        users: layer(__USERS__,__USERS_STROKE__,__USERS_FILL__,' user',' users')};
      window.setMode=function(mode){
        Object.keys(LAYERS).forEach(function(k){
          if(k===mode){LAYERS[k].addTo(MAP);}else{MAP.removeLayer(LAYERS[k]);}});};
      window.setMode(__MODE__);
      setTimeout(function(){MAP.invalidateSize();
        MAP.fitBounds([[S,-180],[N,180]]);
        MAP.setMinZoom(MAP.getZoom());},300);
    })();
    """
    js = (js.replace("__MAP__", m.get_name())
            .replace("__NORTH__", str(LAT_NORTH))
            .replace("__SOUTH__", str(LAT_SOUTH))
            .replace("__LAYER__", json.dumps(basemap_layer))
            .replace("__RUNS__", json.dumps(circle_data(runs, "runs")))
            .replace("__USERS__", json.dumps(circle_data(users, "users")))
            .replace("__RUNS_STROKE__", json.dumps(RUNS_STROKE))
            .replace("__RUNS_FILL__", json.dumps(RUNS_FILL))
            .replace("__USERS_STROKE__", json.dumps(USERS_STROKE))
            .replace("__USERS_FILL__", json.dumps(USERS_FILL))
            .replace("__MODE__", json.dumps(mode)))
    helper = "<script>\n%s\n</script>" % js
    return html.replace("</html>", helper + "\n</html>", 1) if "</html>" in html \
        else html + helper


class WorldMapWindow(QDialog):
    def __init__(self, mw):
        super().__init__(mw)
        self.mw = mw
        self.setWindowTitle("CWatM world map")
        self.setAttribute(Qt.WA_DeleteOnClose)
        # a real top-level window: maximise (and minimise) in the title bar
        self.setWindowFlags(Qt.Window | Qt.WindowTitleHint | Qt.WindowSystemMenuHint
                            | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        self._mode = "runs"
        self._data = {}                     # op -> list, once it arrived
        self._waiting = {"get_run_locations", "get_user_locations"}
        self._loaded = False

        from PySide6.QtWebEngineWidgets import QWebEngineView
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        self.head = QLabel()
        self.head.setStyleSheet(f"color: {theme.c('accent')}; font-size: 18px; "
                                "font-weight: 700;")
        outer.addWidget(self.head)
        self.info = QLabel("Loading…")
        self.info.setStyleSheet(f"color: {theme.c('text_gray')};")
        self.info.setWordWrap(True)
        outer.addWidget(self.info)
        self.web_view = QWebEngineView()
        outer.addWidget(self.web_view, 1)

        row = QHBoxLayout()
        self.btn_runs = self._mode_button("CWatM runs", "runs")
        self.btn_users = self._mode_button("User location", "users")
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        for b in (self.btn_runs, self.btn_users):
            self.group.addButton(b)
            row.addWidget(b)
        row.addStretch(1)
        outer.addLayout(row)
        self.btn_runs.setChecked(True)

        # First size: the map area exactly fits -180..180 x 90N..60S at zoom 1;
        # then the size is released so the window can be resized / maximised.
        self.web_view.setFixedSize(MAP_W, MAP_H)
        self.adjustSize()
        self.web_view.setMinimumSize(200, 120)
        self.web_view.setMaximumSize(QWIDGETSIZE_MAX, QWIDGETSIZE_MAX)
        self._show_texts()

        self.worker = mw.account_worker()
        self.worker.succeeded.connect(self._on_succeeded)
        self.worker.failed.connect(self._on_failed)
        for op in sorted(self._waiting):
            self.worker.submit(op)

    def _mode_button(self, text, mode):
        b = QPushButton(text)
        b.setCheckable(True)
        b.setAutoDefault(False)
        b.setMinimumWidth(130)
        b.setStyleSheet(
            f"QPushButton:checked {{ background-color: {theme.c('accent')}; "
            f"color: {theme.c('menu_sel_text')}; font-weight: 600; }}")
        b.toggled.connect(lambda on, m=mode: on and self._set_mode(m))
        return b

    # ---- mode --------------------------------------------------------------------
    def _set_mode(self, mode):
        self._mode = mode
        self._show_texts()
        if self._loaded:
            self.web_view.page().runJavaScript(f"window.setMode({json.dumps(mode)});")

    def _show_texts(self):
        spec = MODES[self._mode]
        self.head.setText(spec["title"])
        key = "get_run_locations" if self._mode == "runs" else "get_user_locations"
        if key in self._waiting:
            self.info.setText("Loading…")
            return
        rows = self._data.get(key)
        if rows is None:
            self.info.setText("These locations could not be loaded (see gui.log).")
            return
        count_key = "runs" if self._mode == "runs" else "users"
        self.info.setText(spec["info"].format(
            places=len(rows), count=sum(int(r.get(count_key, 0)) for r in rows)))

    # ---- data --------------------------------------------------------------------
    def _on_succeeded(self, op, result):
        if op in self._waiting:
            self._waiting.discard(op)
            self._data[op] = result or []
            self._maybe_show()

    def _on_failed(self, op, code, message):
        if op in self._waiting:
            self._waiting.discard(op)
            self._data[op] = None
            log.info("world map: %s failed: %s (%s)", op, code, message)
            self._maybe_show()

    def _maybe_show(self):
        self._show_texts()
        if self._waiting:
            return
        runs = self._data.get("get_run_locations") or []
        users = self._data.get("get_user_locations") or []
        try:
            from src.gui.widgets.preferences_window import _saved_basemap
            html = build_world_map_html(runs, users, _saved_basemap(self.mw._settings),
                                        self._mode)
        except Exception as e:
            log.warning("world map build failed", exc_info=True)
            self.info.setText(f"The world map could not be built: {e}")
            return
        self.web_view.loadFinished.connect(self._on_loaded)
        try:
            from src.gui.widgets.basin_viewer import _get_tile_handler
            handler = _get_tile_handler()
            handler.set_page(PAGE, html)
            profile = self.web_view.page().profile()
            try:
                profile.removeUrlSchemeHandler(handler)
            except Exception:
                log.debug("world map: no handler to remove", exc_info=True)
            profile.installUrlSchemeHandler(b"osmtile", handler)
            self.web_view.load(QUrl(f"osmtile://{PAGE}/"))
        except Exception:
            # without the shared handler the basemap stays blank behind a proxy,
            # but the circles still show
            log.warning("world map: osmtile serving failed", exc_info=True)
            self.web_view.setHtml(html)  # html-safe: our template + numbers only + pinned Leaflet

    def _on_loaded(self, ok):
        self._loaded = bool(ok)
        if ok:        # a mode switched while the page was loading
            self.web_view.page().runJavaScript(
                f"window.setMode({json.dumps(self._mode)});")


def open_world_map(mw):
    win = getattr(mw, "_world_map_window", None)
    try:
        if win is not None and win.isVisible():
            win.raise_()
            win.activateWindow()
            return win
    except RuntimeError:
        log.debug("previous world map window gone", exc_info=True)
    win = WorldMapWindow(mw)
    mw._world_map_window = win
    win.show()
    return win
