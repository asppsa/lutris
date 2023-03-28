# pylint:disable=using-constant-test
# pylint:disable=comparison-with-callable
from math import floor

import cairo
from gi.repository import GLib, Gtk, Pango, GObject

from lutris.gui.widgets.utils import get_default_icon_path, get_scaled_surface_by_path, get_media_generation_number, \
    get_surface_size, get_runtime_icon_path


class GridViewCellRendererText(Gtk.CellRendererText):
    """CellRendererText adjusted for grid view display, removes extra padding"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.props.alignment = Pango.Alignment.CENTER
        self.props.wrap_mode = Pango.WrapMode.WORD
        self.props.xalign = 0.5
        self.props.yalign = 0

    def set_width(self, width):
        self.props.wrap_width = width


class GridViewCellRendererImage(Gtk.CellRenderer):
    """A pixbuf cell renderer that takes not the pixbuf but a path to an image file;
    it loads that image only when rendering. It also has properties for its width
    and height, so it need not load the pixbuf to know its size."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._cell_width = 0
        self._cell_height = 0
        self._media_path = None
        self._platform = None
        self._is_installed = True
        self.cached_surfaces_new = {}
        self.cached_surfaces_old = {}
        self.cycle_cache_idle_id = None
        self.cached_surface_generation = 0

    @GObject.Property(type=int, default=0)
    def cell_width(self):
        return self._cell_width

    @cell_width.setter
    def cell_width(self, value):
        self._cell_width = value
        self.clear_cache()

    @GObject.Property(type=int, default=0)
    def cell_height(self):
        return self._cell_height

    @cell_height.setter
    def cell_height(self, value):
        self._cell_height = value
        self.clear_cache()

    @GObject.Property(type=str)
    def media_path(self):
        return self._media_path

    @media_path.setter
    def media_path(self, value):
        self._media_path = value

    @GObject.Property(type=str)
    def platform(self):
        return self._platform

    @platform.setter
    def platform(self, value):
        self._platform = value

    @GObject.Property(type=bool, default=True)
    def is_installed(self):
        return self._is_installed

    @is_installed.setter
    def is_installed(self, value):
        self._is_installed = value

    def do_get_size(self, widget, cell_area):
        return 0, 0, self.cell_width, self.cell_height

    def do_render(self, cr, widget, background_area, cell_area, flags):
        cell_width = self.cell_width
        cell_height = self.cell_height
        path = self.media_path
        alpha = 1 if self.is_installed else 100 / 255

        if cell_width > 0 and cell_height > 0 and path:
            surface = self.get_cached_surface_by_path(widget, path)
            if not surface:
                # The default icon needs to be scaled to fill the cell space.
                path = get_default_icon_path((cell_width, cell_height))
                surface = self.get_cached_surface_by_path(widget, path,
                                                          preserve_aspect_ratio=False)

            if surface:
                x, y = self.get_media_position(surface, cell_area)

                if alpha >= 1:
                    self.render_media(cr, widget, surface, x, y)
                    self.render_platforms(cr, widget, x + cell_width, cell_area)
                else:
                    cr.push_group()
                    self.render_media(cr, widget, surface, x, y)
                    self.render_platforms(cr, widget, x + cell_width, cell_area)
                    cr.pop_group_to_source()
                    cr.paint_with_alpha(alpha)

            # Idle time will wait until the widget has drawn whatever it wants to;
            # we can then discard surfaces we aren't using anymore.
            if not self.cycle_cache_idle_id:
                self.cycle_cache_idle_id = GLib.idle_add(self.cycle_cache)

    def get_media_position(self, surface, cell_area):
        width, height = get_surface_size(surface)
        x = round(cell_area.x + (cell_area.width - width) / 2)  # centered
        y = round(cell_area.y + cell_area.height - height)  # at bottom of cell
        return x, y

    def render_media(self, cr, widget, surface, x, y):
        width, height = get_surface_size(surface)

        cr.set_source_surface(surface, x, y)
        cr.get_source().set_extend(cairo.Extend.PAD)  # pylint: disable=no-member
        cr.rectangle(x, y, width, height)
        cr.fill()

    def render_platforms(self, cr, widget, media_right, cell_area):
        platform = self.platform
        if platform and self.cell_height >= 64:
            if "," in platform:
                platforms = platform.split(",")  # pylint:disable=no-member
            else:
                platforms = [platform]

            icon_paths = [get_runtime_icon_path(p + "-symbolic") for p in platforms]
            icon_paths = [path for path in icon_paths if path]
            if icon_paths:
                self.render_badges(cr, widget, icon_paths, (16, 16), media_right, cell_area)

    def render_badges(self, cr, widget, icon_paths, icon_size, media_right, cell_area):
        def render_badge(badge_x, badge_y, path):
            cr.rectangle(badge_x + 1, badge_y + 1, icon_size[0], icon_size[0])
            cr.set_source_rgba(1, 1, 1)
            cr.fill()

            cr.rectangle(badge_x + 0.5, badge_y + 0.5, icon_size[0] + 1, icon_size[0] + 1)
            cr.set_source_rgba(0, 0, 0)
            cr.set_line_width(1)
            cr.stroke()

            icon = self.get_cached_surface_by_path(widget, path, size=icon_size)
            cr.set_source_surface(icon, badge_x + 1, badge_y + 1)
            cr.paint()

        badge_width = icon_size[0] + 2
        badge_height = icon_size[1] + 2

        x = min(media_right, cell_area.x + cell_area.width - badge_width)
        spacing = (cell_area.height - badge_height * len(icon_paths)) / max(1, len(icon_paths) - 1)
        spacing = min(spacing, 1)
        y_offset = floor(badge_height + spacing)
        y = cell_area.y + cell_area.height - badge_height - y_offset * (len(icon_paths) - 1)

        for icon_path in icon_paths:
            render_badge(x, y, icon_path)
            y = y + y_offset

    def clear_cache(self):
        """Discards all cached surfaces; used when some properties are changed."""
        self.cached_surfaces_old.clear()
        self.cached_surfaces_new.clear()

    def cycle_cache(self):
        """Is the key cache size control trick. When called, the surfaces cached or used
        since the last call are preserved, but those not touched are discarded.

        We call this at idle time after rendering a cell; this should keep all the surfaces
        rendered at that time, so during scrolling the visible media are kept and scrolling is smooth.
        At other times we may discard almost all surfaces, saving memory."""
        self.cached_surfaces_old = self.cached_surfaces_new
        self.cached_surfaces_new = {}
        self.cycle_cache_idle_id = None

    def get_cached_surface_by_path(self, widget, path, size=None, preserve_aspect_ratio=True):
        """This obtains the scaled surface to rander for a given media path; this is cached
        in this render, but we'll clear that cache when the media generation number is changed,
        or certain properties are. We also age surfaces from the cache at idle time after
        rendering."""
        if self.cached_surface_generation != get_media_generation_number():
            self.cached_surface_generation = get_media_generation_number()
            self.clear_cache()

        key = widget, path, size, preserve_aspect_ratio

        surface = self.cached_surfaces_new.get(key)
        if surface:
            return surface

        surface = self.cached_surfaces_old.get(key)

        if not surface:
            surface = self.get_surface_by_path(widget, path, size, preserve_aspect_ratio)

        self.cached_surfaces_new[key] = surface
        return surface

    def get_surface_by_path(self, widget, path, size=None, preserve_aspect_ratio=True):
        cell_size = size or (self.cell_width, self.cell_height)
        scale_factor = widget.get_scale_factor() if widget else 1
        return get_scaled_surface_by_path(path, cell_size, scale_factor,
                                          preserve_aspect_ratio=preserve_aspect_ratio)
