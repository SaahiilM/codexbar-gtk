//! X11-only placement for the panel. Wayland position remains compositor-owned.

use gtk::prelude::*;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PanelAnchor {
    /// Optional monitor connector/name supplied by a future tray activation.
    pub monitor: Option<String>,
    /// Optional anchor rectangle in the platform's native coordinate space.
    pub rect: Option<(i32, i32, i32, i32)>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct Rect {
    pub x: i32,
    pub y: i32,
    pub width: i32,
    pub height: i32,
}

pub fn bottom_right_position(
    monitor: Rect,
    workarea: Option<Rect>,
    window: Rect,
    margin: i32,
) -> (i32, i32) {
    let area = workarea
        .and_then(|area| intersection(monitor, area))
        .unwrap_or(monitor);
    (
        area.x + area.width - window.width - margin,
        area.y + area.height - window.height - margin,
    )
}

fn intersection(left: Rect, right: Rect) -> Option<Rect> {
    let x = left.x.max(right.x);
    let y = left.y.max(right.y);
    let right_edge = (left.x + left.width).min(right.x + right.width);
    let bottom_edge = (left.y + left.height).min(right.y + right.height);
    (right_edge > x && bottom_edge > y).then_some(Rect {
        x,
        y,
        width: right_edge - x,
        height: bottom_edge - y,
    })
}

/// Ask the X11 window manager to place the mapped panel inside its selected
/// monitor's EWMH work area. This intentionally does nothing on Wayland.
pub fn place_panel(window: &gtk::ApplicationWindow, _anchor: Option<&PanelAnchor>) -> bool {
    #[cfg(target_os = "linux")]
    {
        unsafe { place_panel_x11(window) }
    }
    #[cfg(not(target_os = "linux"))]
    {
        let _ = window;
        false
    }
}

#[cfg(target_os = "linux")]
unsafe fn place_panel_x11(window: &gtk::ApplicationWindow) -> bool {
    use std::ffi::{c_char, c_int, c_uint, c_ulong, c_void};

    #[link(name = "gtk-4")]
    unsafe extern "C" {
        fn gdk_x11_display_get_xdisplay(display: *mut c_void) -> *mut c_void;
        fn gdk_x11_surface_get_xid(surface: *mut c_void) -> c_ulong;
    }
    #[link(name = "X11")]
    unsafe extern "C" {
        fn XDefaultRootWindow(display: *mut c_void) -> c_ulong;
        fn XInternAtom(display: *mut c_void, name: *const c_char, only_if_exists: c_int)
            -> c_ulong;
        fn XGetGeometry(
            display: *mut c_void,
            drawable: c_ulong,
            root: *mut c_ulong,
            x: *mut c_int,
            y: *mut c_int,
            width: *mut c_uint,
            height: *mut c_uint,
            border_width: *mut c_uint,
            depth: *mut c_uint,
        ) -> c_int;
        fn XMoveWindow(display: *mut c_void, window: c_ulong, x: c_int, y: c_int) -> c_int;
        fn XFlush(display: *mut c_void) -> c_int;
    }
    let Some(surface) = window.surface() else {
        return false;
    };
    let display = surface.display();
    if !display.type_().name().starts_with("GdkX11Display") {
        return false;
    }
    let display_ptr = display.as_ptr().cast::<c_void>();
    let surface_ptr = surface.as_ptr().cast::<c_void>();
    let xdisplay = gdk_x11_display_get_xdisplay(display_ptr);
    let xid = gdk_x11_surface_get_xid(surface_ptr);
    if xdisplay.is_null() || xid == 0 {
        return false;
    }

    let mut monitor = display.monitor_at_surface(&surface).map(|monitor| {
        let rect = monitor.geometry();
        Rect {
            x: rect.x(),
            y: rect.y(),
            width: rect.width(),
            height: rect.height(),
        }
    });
    if monitor
        .as_ref()
        .is_none_or(|rect| rect.width <= 0 || rect.height <= 0)
    {
        if let Some(first) = display
            .monitors()
            .item(0)
            .and_downcast::<gtk::gdk::Monitor>()
        {
            let rect = first.geometry();
            monitor = Some(Rect {
                x: rect.x(),
                y: rect.y(),
                width: rect.width(),
                height: rect.height(),
            });
        }
    }
    let root = XDefaultRootWindow(xdisplay);
    let workarea = read_current_workarea(xdisplay, root, XInternAtom);
    let monitor = monitor
        .filter(|rect| rect.width > 0 && rect.height > 0)
        .or(workarea);
    let Some(monitor) = monitor else {
        return false;
    };
    let mut root_return = 0;
    let mut x = 0;
    let mut y = 0;
    let mut width = 0;
    let mut height = 0;
    let mut border = 0;
    let mut depth = 0;
    if XGetGeometry(
        xdisplay,
        xid,
        &mut root_return,
        &mut x,
        &mut y,
        &mut width,
        &mut height,
        &mut border,
        &mut depth,
    ) == 0
    {
        return false;
    }
    let (target_x, target_y) = bottom_right_position(
        monitor,
        workarea,
        Rect {
            x: 0,
            y: 0,
            width: width as i32,
            height: height as i32,
        },
        12,
    );
    let moved = XMoveWindow(xdisplay, xid, target_x, target_y) != 0;
    let _ = XFlush(xdisplay);
    moved
}

#[cfg(target_os = "linux")]
unsafe fn read_current_workarea(
    display: *mut std::ffi::c_void,
    root: std::ffi::c_ulong,
    intern_atom: unsafe extern "C" fn(
        *mut std::ffi::c_void,
        *const std::ffi::c_char,
        std::ffi::c_int,
    ) -> std::ffi::c_ulong,
) -> Option<Rect> {
    use std::{
        ffi::{c_int, c_long, c_uchar, c_ulong, c_void},
        ptr,
    };
    #[link(name = "X11")]
    unsafe extern "C" {
        fn XGetWindowProperty(
            display: *mut c_void,
            window: c_ulong,
            property: c_ulong,
            long_offset: c_long,
            long_length: c_long,
            delete: c_int,
            requested_type: c_ulong,
            actual_type: *mut c_ulong,
            actual_format: *mut c_int,
            item_count: *mut c_ulong,
            bytes_after: *mut c_ulong,
            property_data: *mut *mut c_uchar,
        ) -> c_int;
        fn XFree(data: *mut c_void) -> c_int;
    }
    let workarea_atom = intern_atom(display, c"_NET_WORKAREA".as_ptr(), 1);
    let desktop_atom = intern_atom(display, c"_NET_CURRENT_DESKTOP".as_ptr(), 1);
    if workarea_atom == 0 || desktop_atom == 0 {
        return None;
    }
    let cardinals = 6; // XA_CARDINAL
    let mut actual = 0;
    let mut format = 0;
    let mut count = 0;
    let mut remaining = 0;
    let mut data = ptr::null_mut();
    let desktop_status = XGetWindowProperty(
        display,
        root,
        desktop_atom,
        0,
        1,
        0,
        cardinals,
        &mut actual,
        &mut format,
        &mut count,
        &mut remaining,
        &mut data,
    );
    let desktop = if desktop_status == 0
        && count > 0
        && !data.is_null()
        && actual == cardinals
        && format == 32
    {
        *(data.cast::<c_ulong>()) as c_long
    } else {
        0
    };
    if !data.is_null() {
        let _ = XFree(data.cast());
        data = ptr::null_mut();
    }
    let status = XGetWindowProperty(
        display,
        root,
        workarea_atom,
        desktop.saturating_mul(4),
        4,
        0,
        cardinals,
        &mut actual,
        &mut format,
        &mut count,
        &mut remaining,
        &mut data,
    );
    if status != 0 || count < 4 || data.is_null() || actual != cardinals || format != 32 {
        if !data.is_null() {
            let _ = XFree(data.cast());
        }
        return None;
    }
    let values = std::slice::from_raw_parts(data.cast::<c_ulong>(), 4);
    let rect = Rect {
        x: values[0] as i32,
        y: values[1] as i32,
        width: values[2] as i32,
        height: values[3] as i32,
    };
    let _ = XFree(data.cast());
    (rect.width > 0 && rect.height > 0).then_some(rect)
}

#[cfg(test)]
mod tests {
    use super::{bottom_right_position, Rect};

    #[test]
    fn placement_uses_workarea_intersected_with_selected_monitor() {
        assert_eq!(
            bottom_right_position(
                Rect {
                    x: 1920,
                    y: 0,
                    width: 1280,
                    height: 1024
                },
                Some(Rect {
                    x: 0,
                    y: 0,
                    width: 3200,
                    height: 960
                }),
                Rect {
                    x: 0,
                    y: 0,
                    width: 420,
                    height: 360
                },
                12,
            ),
            (2768, 588),
        );
    }

    #[test]
    fn placement_falls_back_to_selected_monitor_when_workarea_does_not_intersect() {
        assert_eq!(
            bottom_right_position(
                Rect {
                    x: 0,
                    y: 0,
                    width: 1600,
                    height: 900
                },
                Some(Rect {
                    x: 2000,
                    y: 0,
                    width: 800,
                    height: 860
                }),
                Rect {
                    x: 0,
                    y: 0,
                    width: 420,
                    height: 360
                },
                12,
            ),
            (1168, 528),
        );
    }
}
