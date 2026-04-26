# Bless Hex Editor — Python/GObject-Introspection Port

A faithful Python port of [Bless](https://github.com/ikelos/bless), the GTK3
hex editor originally written in C# by Alexandros Frantzis.

## Architecture

```
bless/
├── buffers/            Piece-table byte buffer engine
│   ├── ibuffer.py        Abstract buffer interface
│   ├── simple_buffer.py  In-memory byte buffer
│   ├── file_buffer.py    Sliding-window file buffer (regular + block devices)
│   ├── segment.py        Segment + intrusive doubly-linked list
│   ├── segment_collection.py  Insert/delete/find on linked segment list
│   ├── actions.py        Reversible mutations (Append/Insert/Delete/Replace/Multi)
│   └── byte_buffer.py    Core editor model: undo/redo, async save, FSW
│
├── util/
│   ├── range.py          Inclusive [start, end] range
│   ├── base_converter.py Base-2..16 string ↔ number conversion
│   └── interval_tree.py  Augmented RB-tree for highlight overlap queries
│
├── tools/
│   ├── preferences.py    XML-backed key/value store with pub/sub
│   └── find.py           BM + Simple find strategies + async FindOperation
│
└── gui/
    ├── drawers.py         Cairo/Pango pre-rendered glyph-strip surfaces
    ├── data_view.py       Edit controller: clipboard, undo cursor, events
    ├── data_view_display.py  GTK widget tree (DrawingArea + VScrollbar)
    ├── data_view_control.py  Keyboard + mouse → cursor/selection/edit
    ├── data_book.py       Gtk.Notebook containing multiple DataViews
    ├── main_window.py     Top-level ApplicationWindow + menus/toolbar
    │
    ├── areas/
    │   ├── area.py            Abstract base for display columns
    │   ├── area_group.py      Synchronized group sharing one buffer view
    │   └── concrete_areas.py  HexArea, AsciiArea, OffsetArea,
    │                          DecimalArea, OctalArea, BinaryArea, SeparatorArea
    │
    └── plugins/
        ├── file_operations.py  New/Open/Save/SaveAs/Revert/Close
        └── find_replace.py     Find & Replace dialog
```

## Key design decisions

| C# original | Python port |
|---|---|
| Piece-table via C# `List<Segment>` | `LinkedList` + `SegmentCollection` in pure Python |
| `System.Threading.Thread` + `AutoResetEvent` | `threading.Thread` + `threading.Event` |
| `FileSystemWatcher` | `watchdog` library (optional) |
| `GLib.Idle.Add(delegate {…})` | `GLib.idle_add(fn)` |
| Cairo `Pixmap` double-buffer | Cairo `ImageSurface` glyph strips |
| C# `event` / `delegate` | Python callback lists |
| `Deque<CursorState>` | `collections.deque` |
| `IntervalTree<T : IRange>` | Generic `IntervalTree[T]` via left-leaning RB-tree |
| `Preferences` XML + `PreferencesProxy` | Identical design, `xml.etree.ElementTree` |
| Plugin system (`GuiPlugin`, `AreaPlugin`) | Replaceable by plain Python imports |

## Running

```bash
# Install dependencies
pip install PyGObject watchdog

# Run directly
python -m bless [file ...]

# Or after pip install -e .
bless [file ...]
```

## Requirements

- Python 3.10+
- GTK 3.x + GObject-Introspection (`python3-gi`, `gir1.2-gtk-3.0`)
- Pango + PangoCairo (`gir1.2-pango-1.0`)
- `watchdog` ≥ 3.0 (optional — enables on-disk change detection)
