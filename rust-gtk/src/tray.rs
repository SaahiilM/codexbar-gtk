//! Native StatusNotifierItem and dbusmenu integration.
//!
//! The item stays on GTK's main context and dispatches every menu action
//! through the application's Gio action group. This keeps tray navigation and
//! shutdown on the same path as buttons and secondary launches.

use std::{cell::RefCell, collections::BTreeMap, rc::Rc};

use gio::prelude::*;

pub const SNI_INTERFACE: &str = "org.kde.StatusNotifierItem";
pub const SNI_SERVICE: &str = "org.kde.StatusNotifierItem-codexbar-gtk";
pub const SNI_PATH: &str = "/StatusNotifierItem";
pub const SNI_WATCHER: &str = "org.kde.StatusNotifierWatcher";
pub const SNI_WATCHER_PATH: &str = "/StatusNotifierWatcher";
pub const SNI_WATCHER_INTERFACE: &str = "org.kde.StatusNotifierWatcher";
pub const MENU_INTERFACE: &str = "com.canonical.dbusmenu";
pub const MENU_PATH: &str = "/MenuBar";

const PROPERTIES_INTERFACE: &str = "org.freedesktop.DBus.Properties";
const DBUS_INTERFACE: &str = "org.freedesktop.DBus";
const DBUS_PATH: &str = "/org/freedesktop/DBus";

const PROTOCOL_XML: &str = r#"
<node>
  <interface name="org.kde.StatusNotifierItem">
    <method name="ContextMenu"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
    <method name="Activate"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
    <method name="SecondaryActivate"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
    <method name="Scroll"><arg name="delta" type="i" direction="in"/><arg name="orientation" type="s" direction="in"/></method>
    <signal name="NewTitle"/>
    <signal name="NewIcon"/>
    <signal name="NewAttentionIcon"/>
    <signal name="NewOverlayIcon"/>
    <signal name="NewToolTip"/>
    <signal name="NewStatus"><arg name="status" type="s"/></signal>
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="WindowId" type="i" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconPixmap" type="a(iiay)" access="read"/>
    <property name="OverlayIconName" type="s" access="read"/>
    <property name="OverlayIconPixmap" type="a(iiay)" access="read"/>
    <property name="AttentionIconName" type="s" access="read"/>
    <property name="AttentionIconPixmap" type="a(iiay)" access="read"/>
    <property name="AttentionMovieName" type="s" access="read"/>
    <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <property name="IconThemePath" type="s" access="read"/>
  </interface>
  <interface name="com.canonical.dbusmenu">
    <method name="GetLayout">
      <arg name="parentId" type="i" direction="in"/>
      <arg name="recursionDepth" type="i" direction="in"/>
      <arg name="propertyNames" type="as" direction="in"/>
      <arg name="revision" type="u" direction="out"/>
      <arg name="layout" type="(ia{sv}av)" direction="out"/>
    </method>
    <method name="GetGroupProperties">
      <arg name="ids" type="ai" direction="in"/>
      <arg name="propertyNames" type="as" direction="in"/>
      <arg name="properties" type="a(ia{sv})" direction="out"/>
    </method>
    <method name="GetProperty"><arg name="id" type="i" direction="in"/><arg name="name" type="s" direction="in"/><arg name="value" type="v" direction="out"/></method>
    <method name="Event"><arg name="id" type="i" direction="in"/><arg name="eventId" type="s" direction="in"/><arg name="data" type="v" direction="in"/><arg name="timestamp" type="u" direction="in"/></method>
    <method name="EventGroup"><arg name="events" type="a(isvu)" direction="in"/><arg name="idErrors" type="ai" direction="out"/></method>
    <method name="AboutToShow"><arg name="id" type="i" direction="in"/><arg name="needUpdate" type="b" direction="out"/></method>
    <method name="AboutToShowGroup"><arg name="ids" type="ai" direction="in"/><arg name="updatesNeeded" type="ai" direction="out"/><arg name="idErrors" type="ai" direction="out"/></method>
    <method name="OnEvent"><arg name="id" type="i" direction="in"/><arg name="eventId" type="s" direction="in"/><arg name="value" type="v" direction="out"/></method>
    <signal name="LayoutUpdated"><arg name="revision" type="u"/><arg name="parent" type="i"/></signal>
    <property name="Version" type="u" access="read"/>
    <property name="TextDirection" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconThemePath" type="as" access="read"/>
  </interface>
</node>
"#;

#[derive(Clone, Debug, PartialEq)]
pub struct TrayPresentation {
    pub icon_name: String,
    pub title: String,
    pub body: String,
    pub pixmap: Option<(i32, i32, Vec<u8>)>,
    pub switcher_rows: Vec<String>,
}

type TrayPixmap = (i32, i32, Vec<u8>);
type TrayTooltip = (String, Vec<TrayPixmap>, String, String);

#[derive(Clone, Debug, PartialEq, Eq)]
struct MenuRow {
    id: i32,
    label: Option<String>,
    action: Option<&'static str>,
}

#[derive(Clone, Debug)]
struct ItemProperties {
    title: String,
    status: String,
    icon_name: String,
    icon_pixmaps: Vec<TrayPixmap>,
    tooltip: TrayTooltip,
}

struct ProtocolState {
    item: ItemProperties,
    menu_rows: Vec<MenuRow>,
    menu_revision: u32,
    registered: bool,
    registering: bool,
    stopped: bool,
    generation: u64,
    watcher_owner: Option<String>,
    registration_cancel: Option<gio::Cancellable>,
}

impl ProtocolState {
    fn new() -> Self {
        let pixmaps = Vec::new();
        Self {
            item: ItemProperties {
                title: "CodexBar".to_owned(),
                status: "Active".to_owned(),
                icon_name: "codexbar-gtk".to_owned(),
                icon_pixmaps: pixmaps.clone(),
                tooltip: (
                    "codexbar-gtk".to_owned(),
                    pixmaps,
                    "CodexBar".to_owned(),
                    String::new(),
                ),
            },
            menu_rows: menu_rows(&[]),
            menu_revision: 1,
            registered: false,
            registering: false,
            stopped: false,
            generation: 0,
            watcher_owner: None,
            registration_cancel: None,
        }
    }
}

/// The owned native tray registration. `stop` is safe to call more than once
/// and releases exported objects, watcher subscriptions, and the stable bus
/// name before the application finishes quitting.
pub struct NativeTray {
    connection: gio::DBusConnection,
    node_info: gio::DBusNodeInfo,
    item_registration: Option<gio::RegistrationId>,
    menu_registration: Option<gio::RegistrationId>,
    watcher_subscription: Option<gio::SignalSubscriptionId>,
    application: gio::Application,
    state: Rc<RefCell<ProtocolState>>,
    owns_name: bool,
    stopped: bool,
}

impl NativeTray {
    pub fn start(application: &gio::Application) -> Result<Self, glib::Error> {
        let connection = gio::bus_get_sync(gio::BusType::Session, None::<&gio::Cancellable>)?;
        let node_info = gio::DBusNodeInfo::for_xml(PROTOCOL_XML)?;
        let state = Rc::new(RefCell::new(ProtocolState::new()));

        let item_interface = node_info
            .lookup_interface(SNI_INTERFACE)
            .expect("SNI interface is in the embedded protocol XML");
        let item_state = state.clone();
        let item_application = application.clone();
        let item_registration = connection
            .register_object(SNI_PATH, &item_interface)
            .method_call(move |connection, _, _, _, method, parameters, invocation| {
                handle_sni_method(
                    &connection,
                    &item_application,
                    &item_state,
                    method,
                    &parameters,
                    invocation,
                );
            })
            .property({
                let state = state.clone();
                move |_, _, _, _, name| sni_property(&state.borrow().item, name)
            })
            .build()?;

        let menu_interface = node_info
            .lookup_interface(MENU_INTERFACE)
            .expect("dbusmenu interface is in the embedded protocol XML");
        let menu_state = state.clone();
        let menu_application = application.clone();
        let menu_registration = connection
            .register_object(MENU_PATH, &menu_interface)
            .method_call(move |connection, _, _, _, method, parameters, invocation| {
                handle_menu_method(
                    &connection,
                    &menu_application,
                    &menu_state,
                    method,
                    &parameters,
                    invocation,
                );
            })
            .property(|_, _, _, _, name| menu_property(name))
            .build()?;

        let owns_name = match request_bus_name(&connection, SNI_SERVICE) {
            Ok(()) => true,
            Err(error) => {
                let _ = connection.unregister_object(item_registration);
                let _ = connection.unregister_object(menu_registration);
                return Err(error);
            }
        };

        let watcher_state = state.clone();
        let watcher_connection = connection.clone();
        let watcher_subscription = connection.signal_subscribe(
            Some(DBUS_INTERFACE),
            Some(DBUS_INTERFACE),
            Some("NameOwnerChanged"),
            Some(DBUS_PATH),
            Some(SNI_WATCHER),
            gio::DBusSignalFlags::NONE,
            move |_, _, _, _, _, parameters| {
                let Some((name, old_owner, new_owner)) =
                    parameters.get::<(String, String, String)>()
                else {
                    return;
                };
                if name != SNI_WATCHER {
                    return;
                }
                watcher_owner_changed(&watcher_connection, &watcher_state, &old_owner, &new_owner);
            },
        );

        if let Ok(owner) = watcher_owner(&connection) {
            let mut current = state.borrow_mut();
            current.watcher_owner = Some(owner);
            drop(current);
            register_with_watcher(&connection, &state, false);
        }

        Ok(Self {
            connection,
            node_info,
            item_registration: Some(item_registration),
            menu_registration: Some(menu_registration),
            watcher_subscription: Some(watcher_subscription),
            application: application.clone(),
            state,
            owns_name,
            stopped: false,
        })
    }

    pub fn update(&self, presentation: TrayPresentation) {
        if self.stopped {
            return;
        }
        let pixmaps = presentation.pixmap.into_iter().collect::<Vec<_>>();
        let tooltip_icon = if pixmaps.is_empty() {
            presentation.icon_name.clone()
        } else {
            String::new()
        };
        let mut properties = self.state.borrow_mut();
        let next_menu_rows = menu_rows(&presentation.switcher_rows);
        let changed_menu = properties.menu_rows != next_menu_rows;
        if changed_menu {
            properties.menu_rows = next_menu_rows;
            properties.menu_revision = properties.menu_revision.wrapping_add(1).max(1);
        }
        let menu_revision = properties.menu_revision;
        let previous_title = properties.item.title.clone();
        let previous_status = properties.item.status.clone();
        let previous_icon_name = properties.item.icon_name.clone();
        let previous_pixmaps = properties.item.icon_pixmaps.clone();
        let previous_tooltip = properties.item.tooltip.clone();

        properties.item.title = presentation.title.clone();
        properties.item.status = "Active".to_owned();
        properties.item.icon_name = presentation.icon_name.clone();
        properties.item.icon_pixmaps = pixmaps.clone();
        properties.item.tooltip = (tooltip_icon, pixmaps, presentation.title, presentation.body);

        let changed_title = previous_title != properties.item.title;
        let changed_status = previous_status != properties.item.status;
        let changed_icon = previous_icon_name != properties.item.icon_name
            || previous_pixmaps != properties.item.icon_pixmaps;
        let changed_tooltip = previous_tooltip != properties.item.tooltip;
        let mut changed = BTreeMap::new();
        if changed_title {
            changed.insert("Title".to_owned(), properties.item.title.to_variant());
        }
        if changed_status {
            changed.insert("Status".to_owned(), properties.item.status.to_variant());
        }
        if changed_icon {
            changed.insert(
                "IconName".to_owned(),
                properties.item.icon_name.to_variant(),
            );
            changed.insert(
                "IconPixmap".to_owned(),
                properties.item.icon_pixmaps.to_variant(),
            );
        }
        if changed_tooltip {
            changed.insert("ToolTip".to_owned(), properties.item.tooltip.to_variant());
        }
        drop(properties);

        if !changed.is_empty() {
            emit_properties_changed(&self.connection, SNI_PATH, SNI_INTERFACE, changed);
        }
        if changed_title {
            emit_empty_signal(&self.connection, SNI_PATH, SNI_INTERFACE, "NewTitle");
        }
        if changed_status {
            let status = self.state.borrow().item.status.clone();
            let _ = self.connection.emit_signal(
                None,
                SNI_PATH,
                SNI_INTERFACE,
                "NewStatus",
                Some(&(status,).to_variant()),
            );
        }
        if changed_icon {
            emit_empty_signal(&self.connection, SNI_PATH, SNI_INTERFACE, "NewIcon");
        }
        if changed_tooltip {
            emit_empty_signal(&self.connection, SNI_PATH, SNI_INTERFACE, "NewToolTip");
        }
        if changed_menu {
            let _ = self.connection.emit_signal(
                None,
                MENU_PATH,
                MENU_INTERFACE,
                "LayoutUpdated",
                Some(&(menu_revision, 0i32).to_variant()),
            );
        }
    }

    pub fn set_status(&self, status: &str) {
        if self.stopped {
            return;
        }
        let changed = {
            let mut state = self.state.borrow_mut();
            if state.item.status == status {
                false
            } else {
                state.item.status = status.to_owned();
                true
            }
        };
        if changed {
            let value = status.to_owned();
            let mut properties = BTreeMap::new();
            properties.insert("Status".to_owned(), value.to_variant());
            emit_properties_changed(&self.connection, SNI_PATH, SNI_INTERFACE, properties);
            let _ = self.connection.emit_signal(
                None,
                SNI_PATH,
                SNI_INTERFACE,
                "NewStatus",
                Some(&(value,).to_variant()),
            );
        }
    }

    pub fn is_registered(&self) -> bool {
        self.state.borrow().registered
    }

    pub fn stop(&mut self) {
        if self.stopped {
            return;
        }
        self.stopped = true;
        {
            let mut state = self.state.borrow_mut();
            state.stopped = true;
            state.generation = state.generation.wrapping_add(1);
            state.registering = false;
            state.registered = false;
            state.watcher_owner = None;
            if let Some(cancellable) = state.registration_cancel.take() {
                cancellable.cancel();
            }
        }
        if let Some(subscription) = self.watcher_subscription.take() {
            self.connection.signal_unsubscribe(subscription);
        }
        if let Some(registration) = self.menu_registration.take() {
            let _ = self.connection.unregister_object(registration);
        }
        if let Some(registration) = self.item_registration.take() {
            let _ = self.connection.unregister_object(registration);
        }
        if self.owns_name {
            let _ = release_bus_name(&self.connection, SNI_SERVICE);
            self.owns_name = false;
        }
        let _ = &self.node_info;
        let _ = &self.application;
    }
}

impl Drop for NativeTray {
    fn drop(&mut self) {
        self.stop();
    }
}

fn request_bus_name(connection: &gio::DBusConnection, name: &str) -> Result<(), glib::Error> {
    let reply = connection.call_sync(
        Some(DBUS_INTERFACE),
        DBUS_PATH,
        DBUS_INTERFACE,
        "RequestName",
        Some(&(name, 4u32).to_variant()),
        Some(glib::VariantTy::new("(u)").expect("RequestName returns one uint")),
        gio::DBusCallFlags::NONE,
        5_000,
        None::<&gio::Cancellable>,
    )?;
    let result = reply.child_get::<u32>(0);
    if result == 1 || result == 4 {
        Ok(())
    } else {
        Err(glib::Error::new(
            gio::IOErrorEnum::Exists,
            &format!("StatusNotifierItem bus name is unavailable ({result})"),
        ))
    }
}

fn release_bus_name(connection: &gio::DBusConnection, name: &str) -> Result<(), glib::Error> {
    connection.call_sync(
        Some(DBUS_INTERFACE),
        DBUS_PATH,
        DBUS_INTERFACE,
        "ReleaseName",
        Some(&(name,).to_variant()),
        Some(glib::VariantTy::new("(u)").expect("ReleaseName returns one uint")),
        gio::DBusCallFlags::NONE,
        5_000,
        None::<&gio::Cancellable>,
    )?;
    Ok(())
}

fn watcher_owner(connection: &gio::DBusConnection) -> Result<String, glib::Error> {
    let reply = connection.call_sync(
        Some(DBUS_INTERFACE),
        DBUS_PATH,
        DBUS_INTERFACE,
        "GetNameOwner",
        Some(&(SNI_WATCHER,).to_variant()),
        Some(glib::VariantTy::new("(s)").expect("GetNameOwner returns one string")),
        gio::DBusCallFlags::NONE,
        2_000,
        None::<&gio::Cancellable>,
    )?;
    Ok(reply.child_get::<String>(0))
}

fn watcher_owner_changed(
    connection: &gio::DBusConnection,
    state: &Rc<RefCell<ProtocolState>>,
    _old_owner: &str,
    new_owner: &str,
) {
    {
        let mut current = state.borrow_mut();
        if current.stopped {
            return;
        }
        current.generation = current.generation.wrapping_add(1);
        current.registered = false;
        current.registering = false;
        current.watcher_owner = (!new_owner.is_empty()).then(|| new_owner.to_owned());
        if let Some(cancellable) = current.registration_cancel.take() {
            cancellable.cancel();
        }
    }
    if !new_owner.is_empty() {
        register_with_watcher(connection, state, false);
    }
}

fn register_with_watcher(
    connection: &gio::DBusConnection,
    state: &Rc<RefCell<ProtocolState>>,
    fallback_path: bool,
) {
    let (generation, argument, cancellable) = {
        let mut current = state.borrow_mut();
        if current.stopped
            || current.watcher_owner.is_none()
            || current.registered
            || current.registering
        {
            return;
        }
        current.registering = true;
        let cancellable = gio::Cancellable::new();
        current.registration_cancel = Some(cancellable.clone());
        (
            current.generation,
            if fallback_path { SNI_PATH } else { SNI_SERVICE },
            cancellable,
        )
    };
    let callback_state = state.clone();
    let callback_connection = connection.clone();
    connection.call(
        Some(SNI_WATCHER),
        SNI_WATCHER_PATH,
        SNI_WATCHER_INTERFACE,
        "RegisterStatusNotifierItem",
        Some(&(argument,).to_variant()),
        None,
        gio::DBusCallFlags::NONE,
        5_000,
        Some(&cancellable),
        move |result| {
            let retry_path = {
                let mut current = callback_state.borrow_mut();
                if current.stopped || current.generation != generation {
                    return;
                }
                current.registration_cancel.take();
                match result {
                    Ok(_) => {
                        current.registered = true;
                        current.registering = false;
                        false
                    }
                    Err(_) if !fallback_path => {
                        current.registering = false;
                        true
                    }
                    Err(_) => {
                        current.registering = false;
                        false
                    }
                }
            };
            if retry_path {
                register_with_watcher(&callback_connection, &callback_state, true);
            }
        },
    );
}

fn sni_property(item: &ItemProperties, name: &str) -> glib::Variant {
    match name {
        "Category" => "ApplicationStatus".to_variant(),
        "Id" => "codexbar-gtk".to_variant(),
        "Title" => item.title.to_variant(),
        "Status" => item.status.to_variant(),
        "WindowId" => 0i32.to_variant(),
        "IconName" => item.icon_name.to_variant(),
        "IconPixmap" => item.icon_pixmaps.to_variant(),
        "OverlayIconName" | "AttentionIconName" => "".to_variant(),
        "OverlayIconPixmap" | "AttentionIconPixmap" => {
            Vec::<(i32, i32, Vec<u8>)>::new().to_variant()
        }
        "AttentionMovieName" | "IconThemePath" => "".to_variant(),
        "ToolTip" => item.tooltip.to_variant(),
        "ItemIsMenu" => false.to_variant(),
        "Menu" => glib::variant::ObjectPath::try_from(MENU_PATH)
            .expect("fixed menu path is valid")
            .to_variant(),
        _ => "".to_variant(),
    }
}

fn menu_property(name: &str) -> glib::Variant {
    match name {
        "Version" => 3u32.to_variant(),
        "TextDirection" => "ltr".to_variant(),
        "Status" => "normal".to_variant(),
        "IconThemePath" => Vec::<String>::new().to_variant(),
        _ => "".to_variant(),
    }
}

fn menu_rows(switcher_rows: &[String]) -> Vec<MenuRow> {
    let mut rows = switcher_rows
        .iter()
        .enumerate()
        .map(|(index, label)| MenuRow {
            id: 100 + index as i32,
            label: Some(label.clone()),
            action: Some("dashboard"),
        })
        .collect::<Vec<_>>();
    if !rows.is_empty() {
        rows.push(MenuRow {
            id: 99,
            label: None,
            action: None,
        });
    }
    rows.extend([
        MenuRow {
            id: 1,
            label: Some("Show usage panel".to_owned()),
            action: Some("panel"),
        },
        MenuRow {
            id: 2,
            label: Some("Refresh".to_owned()),
            action: Some("refresh"),
        },
        MenuRow {
            id: 3,
            label: Some("Open Dashboard".to_owned()),
            action: Some("dashboard"),
        },
        MenuRow {
            id: 4,
            label: None,
            action: None,
        },
        MenuRow {
            id: 5,
            label: Some("Check for updates…".to_owned()),
            action: Some("check-updates"),
        },
        MenuRow {
            id: 6,
            label: Some("Restart CodexBar".to_owned()),
            action: Some("restart"),
        },
        MenuRow {
            id: 7,
            label: Some("Settings…".to_owned()),
            action: Some("settings"),
        },
        MenuRow {
            id: 8,
            label: Some("About CodexBar GTK".to_owned()),
            action: Some("about"),
        },
        MenuRow {
            id: 9,
            label: None,
            action: None,
        },
        MenuRow {
            id: 10,
            label: Some("Quit CodexBar".to_owned()),
            action: Some("quit"),
        },
    ]);
    rows
}

fn menu_item_properties(row: &MenuRow) -> BTreeMap<String, glib::Variant> {
    let mut values = BTreeMap::new();
    if let Some(label) = row.label.as_ref() {
        values.insert("type".to_owned(), "standard".to_variant());
        values.insert("label".to_owned(), label.to_variant());
        values.insert("enabled".to_owned(), true.to_variant());
        values.insert("visible".to_owned(), true.to_variant());
    } else {
        values.insert("type".to_owned(), "separator".to_variant());
        values.insert("visible".to_owned(), true.to_variant());
    }
    values
}

fn layout_node(id: i32, depth: i32, rows: &[MenuRow]) -> glib::Variant {
    let properties = if id == 0 {
        let mut values = BTreeMap::new();
        values.insert("label".to_owned(), "CodexBar".to_variant());
        values.insert("children-display".to_owned(), "submenu".to_variant());
        values
    } else {
        rows.iter()
            .find(|row| row.id == id)
            .map(menu_item_properties)
            .unwrap_or_default()
    };
    let children = if id == 0 && depth != 0 {
        rows.iter()
            .map(|row| layout_node(row.id, depth.saturating_sub(1), rows).to_variant())
            .collect::<Vec<_>>()
    } else {
        Vec::<glib::Variant>::new()
    };
    glib::Variant::tuple_from_iter([
        id.to_variant(),
        properties.to_variant(),
        children.to_variant(),
    ])
}

fn row_action(rows: &[MenuRow], id: i32) -> Option<&'static str> {
    rows.iter().find(|row| row.id == id)?.action
}

fn activate_application_action(application: &gio::Application, action: &str) {
    application.activate_action(action, None);
}

fn handle_sni_method(
    connection: &gio::DBusConnection,
    application: &gio::Application,
    state: &Rc<RefCell<ProtocolState>>,
    method: &str,
    parameters: &glib::Variant,
    invocation: gio::DBusMethodInvocation,
) {
    match method {
        "Activate" | "SecondaryActivate" | "ContextMenu" => {
            let (x, y) = parameters.get::<(i32, i32)>().unwrap_or_default();
            let point = (x, y).to_variant();
            application.activate_action("panel-at", Some(&point));
            invocation.return_value(Some(&().to_variant()));
        }
        // The SNI protocol specifies Scroll(i, s). The Python reference has
        // an older three-argument annotation here; the native export follows
        // the published method signature for host interoperability.
        "Scroll" => invocation.return_value(Some(&().to_variant())),
        _ => {
            invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method);
        }
    }
    let _ = (connection, state);
}

fn handle_menu_method(
    connection: &gio::DBusConnection,
    application: &gio::Application,
    state: &Rc<RefCell<ProtocolState>>,
    method: &str,
    parameters: &glib::Variant,
    invocation: gio::DBusMethodInvocation,
) {
    match method {
        "GetLayout" => {
            let (item_id, depth, _names) =
                parameters
                    .get::<(i32, i32, Vec<String>)>()
                    .unwrap_or((0, -1, Vec::new()));
            let (rows, revision) = {
                let current = state.borrow();
                (current.menu_rows.clone(), current.menu_revision)
            };
            let root_id = if item_id == 0 || rows.iter().any(|row| row.id == item_id) {
                item_id
            } else {
                0
            };
            let depth = if depth < 0 { -1 } else { depth };
            let layout = layout_node(root_id, depth, &rows);
            let result = glib::Variant::tuple_from_iter([revision.to_variant(), layout]);
            invocation.return_value(Some(&result));
        }
        "GetGroupProperties" => {
            let (ids, _names) = parameters
                .get::<(Vec<i32>, Vec<String>)>()
                .unwrap_or_default();
            let rows = state.borrow().menu_rows.clone();
            let values = ids
                .into_iter()
                .filter_map(|id| {
                    let row = rows.iter().find(|row| row.id == id)?;
                    Some((id, menu_item_properties(row)))
                })
                .collect::<Vec<_>>();
            let result = (values,).to_variant();
            invocation.return_value(Some(&result));
        }
        "GetProperty" => {
            let (id, name) = parameters
                .get::<(i32, String)>()
                .unwrap_or((0, String::new()));
            let value = state
                .borrow()
                .menu_rows
                .iter()
                .find(|row| row.id == id)
                .and_then(|row| menu_item_properties(row).remove(&name))
                .unwrap_or_else(|| "".to_variant());
            let result = (value,).to_variant();
            invocation.return_value(Some(&result));
        }
        "Event" => {
            let (id, event, _data, _timestamp) = parameters
                .get::<(i32, String, glib::Variant, u32)>()
                .unwrap_or((0, String::new(), ().to_variant(), 0));
            if matches!(event.as_str(), "clicked" | "activated") {
                let rows = state.borrow().menu_rows.clone();
                if let Some(action) = row_action(&rows, id) {
                    activate_application_action(application, action);
                }
            }
            invocation.return_value(Some(&().to_variant()));
        }
        "EventGroup" => {
            let events = parameters.child_value(0);
            let rows = state.borrow().menu_rows.clone();
            let mut errors = Vec::new();
            for index in 0..events.n_children() {
                let event = events.child_value(index);
                let id = event.child_get::<i32>(0);
                let name = event.child_get::<String>(1);
                if row_action(&rows, id).is_none() {
                    errors.push(id);
                } else if matches!(name.as_str(), "clicked" | "activated") {
                    if let Some(action) = row_action(&rows, id) {
                        activate_application_action(application, action);
                    }
                }
            }
            let result = (errors,).to_variant();
            invocation.return_value(Some(&result));
        }
        "AboutToShow" => {
            let id = parameters.child_get::<i32>(0);
            let known = id == 0 || state.borrow().menu_rows.iter().any(|row| row.id == id);
            invocation.return_value(Some(&(false,).to_variant()));
            if !known {
                // This interface follows libdbusmenu's boolean response; unknown
                // rows remain harmless and do not change the static layout.
            }
        }
        "AboutToShowGroup" => {
            let ids = parameters.child_get::<Vec<i32>>(0);
            let rows = state.borrow().menu_rows.clone();
            let errors = ids
                .into_iter()
                .filter(|id| *id != 0 && !rows.iter().any(|row| row.id == *id))
                .collect::<Vec<_>>();
            invocation.return_value(Some(&(Vec::<i32>::new(), errors).to_variant()));
        }
        "OnEvent" => {
            let value = "".to_variant();
            let result = (value,).to_variant();
            invocation.return_value(Some(&result));
        }
        _ => invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method),
    }
    let _ = connection;
}

fn emit_properties_changed(
    connection: &gio::DBusConnection,
    path: &str,
    interface: &str,
    changed: BTreeMap<String, glib::Variant>,
) {
    let signal = (interface, changed, Vec::<String>::new()).to_variant();
    let _ = connection.emit_signal(
        None,
        path,
        PROPERTIES_INTERFACE,
        "PropertiesChanged",
        Some(&signal),
    );
}

fn emit_empty_signal(connection: &gio::DBusConnection, path: &str, interface: &str, signal: &str) {
    let _ = connection.emit_signal(None, path, interface, signal, Some(&().to_variant()));
}

/// Render a compact StatusNotifierItem pixmap in network byte order ARGB32.
/// Each output pixel is exactly `[alpha, red, green, blue]` as required by SNI.
pub fn meter_pixmap(percent: Option<f64>, accent: &str) -> (i32, i32, Vec<u8>) {
    let level = percent
        .filter(|value| value.is_finite())
        .map(|value| (value.clamp(0.0, 100.0) / 10.0).floor() as u8);
    crate::icons::render_meter(
        level,
        accent,
        crate::icons::RequestedSize {
            width: 32,
            height: 32,
        },
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pixmap_has_network_argb32_shape_and_known_color() {
        let (width, height, pixels) = meter_pixmap(Some(40.0), "#10A37F");
        assert_eq!((width, height), (32, 32));
        assert_eq!(pixels.len(), (width * height * 4) as usize);
        assert!(pixels.chunks(4).any(|pixel| pixel == [255, 16, 163, 127]));
        assert_eq!(&pixels[..4], &[0, 0, 0, 0]);
    }

    #[test]
    fn menu_layout_contains_the_central_actions_and_expected_protocol_shape() {
        let rows = menu_rows(&[]);
        let layout = layout_node(0, -1, &rows);
        assert_eq!(layout.type_().as_str(), "(ia{sv}av)");
        assert_eq!(layout.child_get::<i32>(0), 0);
        assert_eq!(layout.child_value(2).n_children(), 10);
        assert_eq!(row_action(&rows, 1), Some("panel"));
        assert_eq!(row_action(&rows, 7), Some("settings"));
        assert_eq!(row_action(&rows, 8), Some("about"));
        assert_eq!(row_action(&rows, 10), Some("quit"));
        assert_eq!(menu_property("Version").get::<u32>(), Some(3));
    }

    #[test]
    fn switcher_rows_are_accessible_and_keep_stable_action_ids() {
        let rows = menu_rows(&["Codex — Primary 42%".to_owned()]);
        assert_eq!(rows[0].id, 100);
        assert_eq!(rows[0].label.as_deref(), Some("Codex — Primary 42%"));
        assert_eq!(row_action(&rows, 100), Some("dashboard"));
        assert_eq!(rows[1].id, 99);
        assert_eq!(rows[1].label, None);
        assert_eq!(layout_node(0, -1, &rows).child_value(2).n_children(), 12);
    }

    #[test]
    fn protocol_xml_declares_standard_sni_and_menu_signatures() {
        let node = gio::DBusNodeInfo::for_xml(PROTOCOL_XML).unwrap();
        assert!(node.lookup_interface(SNI_INTERFACE).is_some());
        assert!(node.lookup_interface(MENU_INTERFACE).is_some());
        assert!(PROTOCOL_XML.contains(
            "<method name=\"Scroll\"><arg name=\"delta\" type=\"i\" direction=\"in\"/><arg name=\"orientation\" type=\"s\" direction=\"in\"/></method>"
        ));
        assert!(
            PROTOCOL_XML.contains("<arg name=\"layout\" type=\"(ia{sv}av)\" direction=\"out\"/>")
        );
        assert!(PROTOCOL_XML.contains(
            "<arg name=\"updatesNeeded\" type=\"ai\" direction=\"out\"/><arg name=\"idErrors\" type=\"ai\" direction=\"out\"/>"
        ));
    }

    fn session_connection() -> gio::DBusConnection {
        let address = std::env::var("DBUS_SESSION_BUS_ADDRESS")
            .expect("native D-Bus contract test runs in dbus-run-session");
        gio::DBusConnection::for_address_sync(
            &address,
            gio::DBusConnectionFlags::AUTHENTICATION_CLIENT
                | gio::DBusConnectionFlags::MESSAGE_BUS_CONNECTION,
            None,
            None::<&gio::Cancellable>,
        )
        .unwrap()
    }

    fn call(
        connection: &gio::DBusConnection,
        bus_name: Option<&str>,
        path: &str,
        interface: &str,
        method: &str,
        parameters: Option<&glib::Variant>,
    ) -> Result<glib::Variant, glib::Error> {
        let (sender, receiver) = std::sync::mpsc::channel();
        connection.call(
            bus_name,
            path,
            interface,
            method,
            parameters,
            None,
            gio::DBusCallFlags::NONE,
            5_000,
            None::<&gio::Cancellable>,
            move |result| {
                let _ = sender.send(result);
            },
        );
        let context = glib::MainContext::default();
        loop {
            match receiver.try_recv() {
                Ok(result) => return result,
                Err(std::sync::mpsc::TryRecvError::Disconnected) => {
                    panic!("D-Bus call callback disconnected")
                }
                Err(std::sync::mpsc::TryRecvError::Empty) => {
                    context.iteration(true);
                }
            }
        }
    }

    fn bus_name_call(connection: &gio::DBusConnection, method: &str, name: &str) -> u32 {
        let parameters = match method {
            "RequestName" => (name, 4u32).to_variant(),
            "ReleaseName" => (name,).to_variant(),
            _ => panic!("unsupported bus-name helper method: {method}"),
        };
        connection
            .call_sync(
                Some(DBUS_INTERFACE),
                DBUS_PATH,
                DBUS_INTERFACE,
                method,
                Some(&parameters),
                Some(glib::VariantTy::new("(u)").expect("bus-name methods return one uint")),
                gio::DBusCallFlags::NONE,
                5_000,
                None::<&gio::Cancellable>,
            )
            .unwrap()
            .child_get::<u32>(0)
    }

    fn name_has_owner(connection: &gio::DBusConnection, name: &str) -> bool {
        connection
            .call_sync(
                Some(DBUS_INTERFACE),
                DBUS_PATH,
                DBUS_INTERFACE,
                "NameHasOwner",
                Some(&(name,).to_variant()),
                Some(glib::VariantTy::new("(b)").expect("NameHasOwner returns one boolean")),
                gio::DBusCallFlags::NONE,
                5_000,
                None::<&gio::Cancellable>,
            )
            .unwrap()
            .child_get::<bool>(0)
    }

    fn wait_until(mut predicate: impl FnMut() -> bool) {
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(3);
        let context = glib::MainContext::default();
        while !predicate() {
            assert!(
                std::time::Instant::now() < deadline,
                "timed out waiting for private D-Bus event"
            );
            while context.pending() {
                context.iteration(false);
            }
            std::thread::sleep(std::time::Duration::from_millis(5));
        }
    }

    #[test]
    fn private_bus_exports_protocol_dispatches_actions_recovers_and_releases() {
        const WATCHER_XML: &str = r#"
        <node><interface name="org.kde.StatusNotifierWatcher">
          <method name="RegisterStatusNotifierItem"><arg name="service" type="s" direction="in"/></method>
        </interface></node>
        "#;
        let watcher_connection = session_connection();
        assert_eq!(
            bus_name_call(&watcher_connection, "RequestName", SNI_WATCHER),
            1
        );
        let watcher_node = gio::DBusNodeInfo::for_xml(WATCHER_XML).unwrap();
        let watcher_interface = watcher_node
            .lookup_interface(SNI_WATCHER_INTERFACE)
            .unwrap();
        let registrations = Rc::new(RefCell::new(Vec::<String>::new()));
        let watcher_registrations = registrations.clone();
        let watcher_registration = watcher_connection
            .register_object(SNI_WATCHER_PATH, &watcher_interface)
            .method_call(move |_, _, _, _, method, parameters, invocation| {
                if method == "RegisterStatusNotifierItem" {
                    let (service,) = parameters.get::<(String,)>().unwrap();
                    watcher_registrations.borrow_mut().push(service.clone());
                    if service == SNI_SERVICE {
                        invocation.return_dbus_error(
                            "org.example.TrayTest.RejectedName",
                            "exercise object-path fallback",
                        );
                        return;
                    }
                }
                invocation.return_value(Some(&().to_variant()));
            })
            .build()
            .unwrap();

        let application = gio::Application::new(
            Some("org.example.CodexBarTrayContractTest"),
            gio::ApplicationFlags::NON_UNIQUE,
        );
        application.register(None::<&gio::Cancellable>).unwrap();
        let action_hits = Rc::new(RefCell::new(Vec::<(String, Option<(i32, i32)>)>::new()));
        for name in [
            "panel",
            "refresh",
            "dashboard",
            "check-updates",
            "restart",
            "settings",
            "about",
            "quit",
        ] {
            let action = gio::SimpleAction::new(name, None);
            let hits = action_hits.clone();
            action.connect_activate(move |_, _| hits.borrow_mut().push((name.to_owned(), None)));
            application.add_action(&action);
        }
        let panel_at =
            gio::SimpleAction::new("panel-at", Some(glib::VariantTy::new("(ii)").unwrap()));
        let panel_hits = action_hits.clone();
        panel_at.connect_activate(move |_, parameter| {
            let point = parameter
                .and_then(|value| value.get::<(i32, i32)>())
                .unwrap();
            panel_hits
                .borrow_mut()
                .push(("panel-at".to_owned(), Some(point)));
        });
        application.add_action(&panel_at);

        let mut tray = NativeTray::start(&application).unwrap();
        wait_until(|| registrations.borrow().len() == 2 && tray.is_registered());
        assert_eq!(registrations.borrow()[0], SNI_SERVICE);
        assert_eq!(registrations.borrow()[1], SNI_PATH);

        let caller = session_connection();
        let introspection = call(
            &caller,
            Some(SNI_SERVICE),
            SNI_PATH,
            "org.freedesktop.DBus.Introspectable",
            "Introspect",
            Some(&().to_variant()),
        )
        .unwrap()
        .child_get::<String>(0);
        assert!(introspection.contains("name=\"Scroll\""));
        assert!(introspection.contains("name=\"delta\""));
        assert!(introspection.contains("type=\"i\""));

        let all_properties = call(
            &caller,
            Some(SNI_SERVICE),
            SNI_PATH,
            PROPERTIES_INTERFACE,
            "GetAll",
            Some(&(SNI_INTERFACE,).to_variant()),
        )
        .unwrap();
        let properties = all_properties
            .child_value(0)
            .get::<BTreeMap<String, glib::Variant>>()
            .unwrap();
        assert_eq!(
            properties["Category"].get::<String>().as_deref(),
            Some("ApplicationStatus")
        );
        assert_eq!(properties["Menu"].type_().as_str(), "o");
        assert_eq!(properties["ToolTip"].type_().as_str(), "(sa(iiay)ss)");

        let layout = call(
            &caller,
            Some(SNI_SERVICE),
            MENU_PATH,
            MENU_INTERFACE,
            "GetLayout",
            Some(&(0i32, -1i32, Vec::<String>::new()).to_variant()),
        )
        .unwrap();
        assert_eq!(layout.type_().as_str(), "(u(ia{sv}av))");
        assert_eq!(layout.child_get::<u32>(0), 1);
        assert_eq!(layout.child_value(1).child_value(2).n_children(), 10);
        let group_properties = call(
            &caller,
            Some(SNI_SERVICE),
            MENU_PATH,
            MENU_INTERFACE,
            "GetGroupProperties",
            Some(&(vec![1i32, 2], Vec::<String>::new()).to_variant()),
        )
        .unwrap();
        assert_eq!(group_properties.type_().as_str(), "(a(ia{sv}))");
        let about = call(
            &caller,
            Some(SNI_SERVICE),
            MENU_PATH,
            MENU_INTERFACE,
            "AboutToShow",
            Some(&(0i32,).to_variant()),
        )
        .unwrap();
        assert_eq!(about.type_().as_str(), "(b)");
        assert!(!about.child_get::<bool>(0));
        let about_group = call(
            &caller,
            Some(SNI_SERVICE),
            MENU_PATH,
            MENU_INTERFACE,
            "AboutToShowGroup",
            Some(&(vec![0i32, 41],).to_variant()),
        )
        .unwrap();
        assert_eq!(about_group.type_().as_str(), "(aiai)");
        assert_eq!(about_group.child_get::<Vec<i32>>(0), Vec::<i32>::new());
        assert_eq!(about_group.child_get::<Vec<i32>>(1), vec![41]);
        let on_event = call(
            &caller,
            Some(SNI_SERVICE),
            MENU_PATH,
            MENU_INTERFACE,
            "OnEvent",
            Some(&(8i32, "opened").to_variant()),
        )
        .unwrap();
        assert_eq!(on_event.type_().as_str(), "(v)");
        assert_eq!(
            on_event
                .child_value(0)
                .get::<glib::Variant>()
                .unwrap()
                .get::<String>(),
            Some(String::new())
        );
        let label = call(
            &caller,
            Some(SNI_SERVICE),
            MENU_PATH,
            MENU_INTERFACE,
            "GetProperty",
            Some(&(2i32, "label").to_variant()),
        )
        .unwrap();
        assert_eq!(label.type_().as_str(), "(v)");
        let label_value = label.child_value(0).get::<glib::Variant>().unwrap();
        assert_eq!(label_value.get::<String>().as_deref(), Some("Refresh"));
        let about_label = call(
            &caller,
            Some(SNI_SERVICE),
            MENU_PATH,
            MENU_INTERFACE,
            "GetProperty",
            Some(&(8i32, "label").to_variant()),
        )
        .unwrap()
        .child_value(0)
        .get::<glib::Variant>()
        .unwrap();
        assert_eq!(
            about_label.get::<String>().as_deref(),
            Some("About CodexBar GTK")
        );

        let observed = Rc::new(RefCell::new(Vec::<(String, String)>::new()));
        let observed_signals = observed.clone();
        let subscription = caller.signal_subscribe(
            Some(SNI_SERVICE),
            None,
            None,
            Some(SNI_PATH),
            None,
            gio::DBusSignalFlags::NONE,
            move |_, _, _, _, member, parameters| {
                observed_signals
                    .borrow_mut()
                    .push((member.to_owned(), parameters.type_().as_str().to_owned()));
            },
        );
        let observed_layout = Rc::new(RefCell::new(Vec::<String>::new()));
        let layout_signals = observed_layout.clone();
        let layout_subscription = caller.signal_subscribe(
            Some(SNI_SERVICE),
            Some(MENU_INTERFACE),
            Some("LayoutUpdated"),
            Some(MENU_PATH),
            None,
            gio::DBusSignalFlags::NONE,
            move |_, _, _, _, _, parameters| {
                layout_signals
                    .borrow_mut()
                    .push(parameters.type_().as_str().to_owned());
            },
        );
        tray.update(TrayPresentation {
            icon_name: String::new(),
            title: "CodexBar GTK · Synthetic".to_owned(),
            body: "Synthetic provider: 42%".to_owned(),
            pixmap: Some(meter_pixmap(Some(42.0), "#10A37F")),
            switcher_rows: vec!["Codex — Primary 42%".to_owned()],
        });
        tray.set_status("Passive");
        wait_until(|| {
            observed
                .borrow()
                .iter()
                .any(|(name, _)| name == "NewStatus")
        });
        let signals = observed.borrow();
        assert!(signals
            .iter()
            .any(|(name, signature)| { name == "PropertiesChanged" && signature == "(sa{sv}as)" }));
        assert!(signals
            .iter()
            .any(|(name, signature)| name == "NewTitle" && signature == "()"));
        assert!(signals
            .iter()
            .any(|(name, signature)| name == "NewIcon" && signature == "()"));
        assert!(signals
            .iter()
            .any(|(name, signature)| name == "NewToolTip" && signature == "()"));
        assert!(signals
            .iter()
            .any(|(name, signature)| name == "NewStatus" && signature == "(s)"));
        drop(signals);
        wait_until(|| !observed_layout.borrow().is_empty());
        assert_eq!(observed_layout.borrow().as_slice(), &["(ui)".to_owned()]);
        let switched_layout = call(
            &caller,
            Some(SNI_SERVICE),
            MENU_PATH,
            MENU_INTERFACE,
            "GetLayout",
            Some(&(0i32, -1i32, Vec::<String>::new()).to_variant()),
        )
        .unwrap();
        assert_eq!(switched_layout.child_get::<u32>(0), 2);
        assert_eq!(
            switched_layout.child_value(1).child_value(2).n_children(),
            12
        );
        let switcher_label = call(
            &caller,
            Some(SNI_SERVICE),
            MENU_PATH,
            MENU_INTERFACE,
            "GetProperty",
            Some(&(100i32, "label").to_variant()),
        )
        .unwrap()
        .child_value(0)
        .get::<glib::Variant>()
        .unwrap();
        assert_eq!(
            switcher_label.get::<String>().as_deref(),
            Some("Codex — Primary 42%")
        );

        let refreshed_properties = call(
            &caller,
            Some(SNI_SERVICE),
            SNI_PATH,
            PROPERTIES_INTERFACE,
            "GetAll",
            Some(&(SNI_INTERFACE,).to_variant()),
        )
        .unwrap();
        let refreshed_properties = refreshed_properties
            .child_value(0)
            .get::<BTreeMap<String, glib::Variant>>()
            .unwrap();
        let pixmaps = refreshed_properties["IconPixmap"]
            .get::<Vec<(i32, i32, Vec<u8>)>>()
            .unwrap();
        assert_eq!((pixmaps[0].0, pixmaps[0].1), (32, 32));
        assert_eq!(pixmaps[0].2.len(), 32 * 32 * 4);
        let tooltip = refreshed_properties["ToolTip"]
            .get::<(String, Vec<(i32, i32, Vec<u8>)>, String, String)>()
            .unwrap();
        assert_eq!(tooltip.0, "");
        assert_eq!(tooltip.2, "CodexBar GTK · Synthetic");
        assert_eq!(tooltip.3, "Synthetic provider: 42%");

        call(
            &caller,
            Some(SNI_SERVICE),
            SNI_PATH,
            SNI_INTERFACE,
            "Activate",
            Some(&(31i32, 47i32).to_variant()),
        )
        .unwrap();
        assert!(action_hits
            .borrow()
            .contains(&("panel-at".to_owned(), Some((31, 47)))));
        for method in ["SecondaryActivate", "ContextMenu"] {
            call(
                &caller,
                Some(SNI_SERVICE),
                SNI_PATH,
                SNI_INTERFACE,
                method,
                Some(&(53i32, 61i32).to_variant()),
            )
            .unwrap();
        }
        assert!(action_hits
            .borrow()
            .contains(&("panel-at".to_owned(), Some((53, 61)))));
        call(
            &caller,
            Some(SNI_SERVICE),
            SNI_PATH,
            SNI_INTERFACE,
            "Scroll",
            Some(&(1i32, "vertical").to_variant()),
        )
        .unwrap();
        for (id, name) in [
            (1, "panel"),
            (2, "refresh"),
            (3, "dashboard"),
            (5, "check-updates"),
            (6, "restart"),
            (7, "settings"),
            (8, "about"),
            (100, "dashboard"),
            (10, "quit"),
        ] {
            call(
                &caller,
                Some(SNI_SERVICE),
                MENU_PATH,
                MENU_INTERFACE,
                "Event",
                Some(&(id, "clicked", "".to_variant(), 0u32).to_variant()),
            )
            .unwrap();
            assert!(action_hits
                .borrow()
                .iter()
                .any(|(action, _)| action == name));
        }
        let grouped_events = vec![
            (2i32, "clicked", "".to_variant(), 0u32),
            (7i32, "clicked", "".to_variant(), 0u32),
            (41i32, "opened", "".to_variant(), 0u32),
        ];
        let group_result = call(
            &caller,
            Some(SNI_SERVICE),
            MENU_PATH,
            MENU_INTERFACE,
            "EventGroup",
            Some(&(grouped_events,).to_variant()),
        )
        .unwrap();
        assert_eq!(group_result.type_().as_str(), "(ai)");
        assert_eq!(group_result.child_get::<Vec<i32>>(0), vec![41]);

        assert_eq!(
            bus_name_call(&watcher_connection, "ReleaseName", SNI_WATCHER),
            1
        );
        wait_until(|| !tray.is_registered());
        assert_eq!(
            bus_name_call(&watcher_connection, "RequestName", SNI_WATCHER),
            1
        );
        wait_until(|| registrations.borrow().len() == 4 && tray.is_registered());
        assert_eq!(registrations.borrow()[2], SNI_SERVICE);
        assert_eq!(registrations.borrow()[3], SNI_PATH);

        tray.stop();
        tray.stop();
        assert!(!tray.is_registered());
        assert!(!name_has_owner(&caller, SNI_SERVICE));
        assert_eq!(
            bus_name_call(&watcher_connection, "ReleaseName", SNI_WATCHER),
            1
        );
        assert_eq!(
            bus_name_call(&watcher_connection, "RequestName", SNI_WATCHER),
            1
        );
        let deadline = std::time::Instant::now() + std::time::Duration::from_millis(100);
        let context = glib::MainContext::default();
        while std::time::Instant::now() < deadline {
            while context.pending() {
                context.iteration(false);
            }
            std::thread::sleep(std::time::Duration::from_millis(5));
        }
        assert_eq!(
            registrations.borrow().len(),
            4,
            "stopped tray must not re-register"
        );

        caller.signal_unsubscribe(subscription);
        caller.signal_unsubscribe(layout_subscription);
        let _ = watcher_connection.unregister_object(watcher_registration);
        let _ = bus_name_call(&watcher_connection, "ReleaseName", SNI_WATCHER);
    }
}
