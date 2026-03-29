import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const PROFILE_HELPER = '/usr/local/bin/oxp-fan-profile';
const RGB_HELPER = '/usr/local/bin/oxp-rgb';
const RGB_HID_HELPER = '/usr/local/bin/oxp-rgb-hid';
const TDP_HELPER = '/usr/local/bin/oxp-tdp';
const BATTERY_HELPER = '/usr/local/bin/oxp-battery-probe';
const BATTERY_EC_HELPER = '/usr/local/bin/oxp-battery-ec-probe';
const CONFIG_PATH = GLib.build_filenamev([GLib.get_user_config_dir(), 'oxp-control.json']);
const DEFAULT_COLOR = [244, 67, 54];
const DEFAULT_NOTIFICATION_COLOR = [255, 215, 0];
const NOTIFICATION_FLASH_PATTERN_MS = 500;
const DEFAULT_TDP_WATTS = 15;
const SAFE_BATTERY_TDP_WATTS = 65;
const MAX_BATTERY_TDP_WATTS = 80;
const TDP_WARNING_WATTS = 80;
const TDP_ACTIONS = [8, 10, 12, 15, 18, 20, 25, 28, 35, 45, 65, 80, 90, 100, 120];
const CHARGE_LIMIT_ACTIONS = [50, 60, 70, 75, 80, 85, 90, 95, 100];
const BYPASS_ACTIONS = [
    {label: 'Off', value: 'off'},
    {label: 'Mode 1', value: 'mode1'},
    {label: 'Mode 2', value: 'mode2'},
];

const QUICK_COLORS = [
    {label: 'Pick Color…', kind: 'picker'},
    {label: 'Last Custom', kind: 'last-custom'},
    {label: 'Warm', preset: 'warm'},
    {label: 'Red', preset: 'red'},
    {label: 'Green', preset: 'green'},
    {label: 'Blue', preset: 'blue'},
    {label: 'Off', preset: 'off'},
];

const BRIGHTNESS_ACTIONS = [
    {label: 'Dim', preset: 'dim'},
    {label: 'Mid', preset: 'mid'},
    {label: 'Bright', preset: 'bright'},
];

const EFFECT_ACTIONS = [
    {label: 'Rainbow', preset: 'rainbow'},
    {label: 'Rainbow Flow', preset: 'rainbow-flow'},
    {label: 'Rainbow Breath', preset: 'rainbow-breath-random'},
    {label: 'Rainbow Cycle', preset: 'rainbow-cycle'},
    {label: 'Whole Rainbow', preset: 'whole-rainbow-cycle'},
    {label: 'Flame Cycle', preset: 'flame-cycle'},
    {label: 'Cyberpunk', preset: 'cyberpunk'},
];

const MONO_ACTIONS = [
    {label: 'Green Breath', preset: 'green-breath'},
    {label: 'Cyan Breath', preset: 'cyan-breath'},
    {label: 'Pink Breath', preset: 'pink-breath'},
    {label: 'White Breath', preset: 'white-breath-slow'},
    {label: 'Red Monster', preset: 'red-monster'},
    {label: 'Green Monster', preset: 'green-monster'},
    {label: 'Blue Monster', preset: 'blue-monster'},
];

const TEXT_DECODER = new TextDecoder('utf-8');

function rgbToHex(red, green, blue) {
    return '#' + [red, green, blue].map(value => value.toString(16).padStart(2, '0')).join('');
}

function parseColorOutput(text) {
    const trimmed = text.trim();
    let match = trimmed.match(/^#?([0-9a-fA-F]{6})$/);
    if (match) {
        const hex = match[1];
        return [
            parseInt(hex.slice(0, 2), 16),
            parseInt(hex.slice(2, 4), 16),
            parseInt(hex.slice(4, 6), 16),
        ];
    }

    match = trimmed.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/i);
    if (match) {
        return [parseInt(match[1], 10), parseInt(match[2], 10), parseInt(match[3], 10)];
    }

    return null;
}

function formatEnergyWh(rawValue) {
    const parsed = Number.parseInt(rawValue, 10);
    if (Number.isNaN(parsed)) {
        return 'n/a';
    }
    return `${(parsed / 1000000).toFixed(2)} Wh`;
}

function sanitizeRgb(rgb, fallback) {
    if (!Array.isArray(rgb) || rgb.length !== 3) {
        return fallback;
    }
    return rgb.map((value, index) => {
        const base = fallback[index];
        const parsed = Number.parseInt(value, 10);
        if (Number.isNaN(parsed)) {
            return base;
        }
        return Math.max(0, Math.min(255, parsed));
    });
}

function decodeBytes(bytes) {
    if (typeof bytes === 'string') {
        return bytes;
    }
    return TEXT_DECODER.decode(bytes);
}

function defaultRgbState() {
    return {
        kind: 'preset',
        preset: 'warm',
        label: 'Warm',
    };
}

function rgbStateLabel(state) {
    if (!state) {
        return 'none';
    }
    if (state.kind === 'custom') {
        return state.label || rgbToHex(...state.rgb);
    }
    return state.label || state.preset || 'unknown';
}

const OXPFanProfilesButton = GObject.registerClass(
class OXPFanProfilesButton extends PanelMenu.Button {
    _init() {
        super._init(0.0, 'OXP Control');

        this._icon = new St.Icon({
            icon_name: 'weather-windy-symbolic',
            style_class: 'system-status-icon',
            y_align: Clutter.ActorAlign.CENTER,
        });
        this.add_child(this._icon);

        this._config = this._loadConfig();
        this._batteryEcLoaded = false;
        this._batteryBackendAvailable = null;
        this._currentFanProfile = null;
        this._notificationFlashTimeoutId = null;
        this._notificationFlashStepIds = [];
        this._notificationSourceSignals = new Map();
        this._messageTraySignals = [];
        this._upowerProxy = null;
        this._upowerSignalId = 0;
        this.menu.connect('open-state-changed', (_menu, open) => {
            if (open) {
                this._refreshBatteryInfo(true);
            }
        });

        this._summaryBox = new St.BoxLayout({
            vertical: true,
            style: 'padding: 8px 12px; spacing: 4px;',
        });
        this._statusItem = new St.Label({
            text: 'Loading…',
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._tdpStateItem = new St.Label({
            text: '',
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._rgbStateItem = new St.Label({
            text: '',
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._summaryBox.add_child(this._statusItem);
        this._summaryBox.add_child(this._tdpStateItem);
        this._summaryBox.add_child(this._rgbStateItem);
        this.menu.box.add_child(this._summaryBox);
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        this._profilesMenu = new PopupMenu.PopupSubMenuMenuItem('Fan Profiles');
        this.menu.addMenuItem(this._profilesMenu);

        this._tdpMenu = new PopupMenu.PopupSubMenuMenuItem('TDP');
        this.menu.addMenuItem(this._tdpMenu);

        this._batteryMenu = new PopupMenu.PopupSubMenuMenuItem('Battery');
        this.menu.addMenuItem(this._batteryMenu);
        this._batteryHealthItem = new PopupMenu.PopupMenuItem('Health: …', {
            reactive: false,
            can_focus: false,
        });
        this._batteryMenu.menu.addMenuItem(this._batteryHealthItem);
        this._batteryEnergyItem = new PopupMenu.PopupMenuItem('Energy: …', {
            reactive: false,
            can_focus: false,
        });
        this._batteryMenu.menu.addMenuItem(this._batteryEnergyItem);
        this._batteryLimitItem = new PopupMenu.PopupMenuItem('Charge Limit: …', {
            reactive: false,
            can_focus: false,
        });
        this._batteryMenu.menu.addMenuItem(this._batteryLimitItem);
        this._batteryModeItem = new PopupMenu.PopupMenuItem('Power Mode: …', {
            reactive: false,
            can_focus: false,
        });
        this._batteryMenu.menu.addMenuItem(this._batteryModeItem);

        this._batteryChargeMenu = new PopupMenu.PopupSubMenuMenuItem('Charge Limit');
        this.menu.addMenuItem(this._batteryChargeMenu);
        this._batteryBypassMenu = new PopupMenu.PopupSubMenuMenuItem('Bypass Mode');
        this.menu.addMenuItem(this._batteryBypassMenu);
        this._colorsMenu = new PopupMenu.PopupSubMenuMenuItem('Colors');
        this.menu.addMenuItem(this._colorsMenu);
        this._quickColorsSection = this._colorsMenu.menu;

        this._effectsMenu = new PopupMenu.PopupSubMenuMenuItem('Effects');
        this.menu.addMenuItem(this._effectsMenu);
        this._effectsSection = this._effectsMenu.menu;

        this._monoMenu = new PopupMenu.PopupSubMenuMenuItem('Monochrome');
        this.menu.addMenuItem(this._monoMenu);
        this._monoSection = this._monoMenu.menu;

        this._notificationMenu = new PopupMenu.PopupSubMenuMenuItem('Notifications');
        this.menu.addMenuItem(this._notificationMenu);
        this._notificationToggle = new PopupMenu.PopupSwitchMenuItem(
            'Flash On Notifications',
            this._config.notificationFlashEnabled
        );
        this._notificationToggle.connect('toggled', (_item, state) => {
            this._config.notificationFlashEnabled = state;
            this._saveConfig();
            this._updateInfoRows();
        });
        this._notificationMenu.menu.addMenuItem(this._notificationToggle);

        this._notificationColorItem = new PopupMenu.PopupMenuItem('Notification Color…');
        this._notificationColorItem.connect('activate', () => this._openNotificationColorPicker());
        this._notificationMenu.menu.addMenuItem(this._notificationColorItem);

        this._testFlashItem = new PopupMenu.PopupMenuItem('Test Notification Flash');
        this._testFlashItem.connect('activate', () => this._flashNotificationColor());
        this._notificationMenu.menu.addMenuItem(this._testFlashItem);

        this._buildTdpMenu();
        this._buildBatteryMenus();
        this._buildRgbMenu();
        this._connectNotificationSignals();
        this._connectPowerSignals();
        this._refresh();
        this._updateInfoRows();
        this._timeoutId = GLib.timeout_add_seconds(
            GLib.PRIORITY_DEFAULT,
            10,
            () => {
                this._refresh();
                return GLib.SOURCE_CONTINUE;
            }
        );
    }

    _loadConfig() {
        const fallback = {
            lastColor: DEFAULT_COLOR,
            notificationColor: DEFAULT_NOTIFICATION_COLOR,
            notificationFlashEnabled: false,
            currentRgbState: defaultRgbState(),
            currentTdpWatts: DEFAULT_TDP_WATTS,
        };

        try {
            const [ok, contents] = GLib.file_get_contents(CONFIG_PATH);
            if (!ok) {
                return fallback;
            }
            const parsed = JSON.parse(decodeBytes(contents));
            return {
                lastColor: sanitizeRgb(parsed.lastColor, DEFAULT_COLOR),
                notificationColor: sanitizeRgb(parsed.notificationColor, DEFAULT_NOTIFICATION_COLOR),
                notificationFlashEnabled: Boolean(parsed.notificationFlashEnabled),
                currentRgbState: parsed.currentRgbState || defaultRgbState(),
                currentTdpWatts: Number.parseInt(parsed.currentTdpWatts, 10) || DEFAULT_TDP_WATTS,
            };
        } catch (error) {
            return fallback;
        }
    }

    _saveConfig() {
        try {
            GLib.mkdir_with_parents(GLib.get_user_config_dir(), 0o755);
            GLib.file_set_contents(CONFIG_PATH, JSON.stringify(this._config, null, 2) + '\n');
        } catch (error) {
            log(`OXP config save error: ${error}`);
        }
    }

    _updateInfoRows() {
        const rgbLabel = rgbStateLabel(this._config.currentRgbState);
        const tdpLabel = `${this._config.currentTdpWatts || DEFAULT_TDP_WATTS}W`;
        const fanLabel = this._currentFanProfile || '…';
        this._statusItem.text = `Fan: ${fanLabel}`;
        this._rgbStateItem.text = `RGB: ${rgbLabel}`;
        if (this._tdpStateItem) {
            this._tdpStateItem.text = `TDP: ${tdpLabel}`;
        }
    }

    _runStatus() {
        try {
            const proc = Gio.Subprocess.new(
                [PROFILE_HELPER, 'status'],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE
            );
            const [, stdout, stderr] = proc.communicate_utf8(null, null);
            if (proc.get_exit_status() !== 0) {
                throw new Error(stderr.trim() || 'profile helper failed');
            }
            return JSON.parse(stdout);
        } catch (error) {
            log(`OXP control status error: ${error}`);
            return null;
        }
    }

    _readTextFile(path) {
        try {
            const [ok, bytes] = GLib.file_get_contents(path);
            if (!ok) {
                return null;
            }
            return decodeBytes(bytes).trim();
        } catch (_error) {
            return null;
        }
    }

    _readSysfsBatteryInfo() {
        const base = '/sys/class/power_supply/BAT0';
        const energyFull = this._readTextFile(`${base}/energy_full`);
        const energyFullDesign = this._readTextFile(`${base}/energy_full_design`);
        const capacity = this._readTextFile(`${base}/capacity`);
        let healthPercent = null;

        if (energyFull && energyFullDesign) {
            const full = Number.parseInt(energyFull, 10);
            const design = Number.parseInt(energyFullDesign, 10);
            if (!Number.isNaN(full) && !Number.isNaN(design) && design > 0) {
                healthPercent = (full * 100.0 / design).toFixed(2);
            }
        }

        return {
            energyFull,
            energyFullDesign,
            capacity,
            healthPercent,
        };
    }

    _readPowerSourceInfo() {
        if (this._upowerProxy) {
            try {
                const onBattery = this._upowerProxy.get_cached_property('OnBattery')?.unpack();
                if (typeof onBattery === 'boolean') {
                    return {onAc: !onBattery, onBattery};
                }
            } catch (_error) {
            }
        }

        const acOnline = this._readTextFile('/sys/class/power_supply/ACAD/online');
        if (acOnline === '1') {
            return {onAc: true, onBattery: false};
        }
        if (acOnline === '0') {
            return {onAc: false, onBattery: true};
        }

        const batteryStatus = this._readTextFile('/sys/class/power_supply/BAT0/status');
        if (batteryStatus === 'Discharging') {
            return {onAc: false, onBattery: true};
        }

        return {onAc: false, onBattery: false};
    }

    _connectPowerSignals() {
        try {
            this._upowerProxy = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SYSTEM,
                Gio.DBusProxyFlags.NONE,
                null,
                'org.freedesktop.UPower',
                '/org/freedesktop/UPower',
                'org.freedesktop.UPower',
                null
            );
            this._upowerSignalId = this._upowerProxy.connect('g-properties-changed', () => {
                const power = this._enforceBatteryTdpSafety();
                this._buildTdpMenu();
                if (power.onBattery) {
                    this._statusItem.text = `On battery: capped at ${MAX_BATTERY_TDP_WATTS}W`;
                }
            });
        } catch (error) {
            log(`OXP UPower signal error: ${error}`);
        }
    }

    _runBatteryProbe() {
        try {
            const proc = Gio.Subprocess.new(
                [BATTERY_EC_HELPER],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE
            );
            const [, stdout, stderr] = proc.communicate_utf8(null, null);
            if (proc.get_exit_status() !== 0) {
                throw new Error(stderr.trim() || 'battery helper failed');
            }
            return JSON.parse(stdout);
        } catch (error) {
            log(`OXP battery probe error: ${error}`);
            return null;
        }
    }

    _refreshBatteryInfo(withEc = false) {
        const sysfs = this._readSysfsBatteryInfo();
        const health = sysfs.healthPercent ?? 'n/a';
        const energyFull = formatEnergyWh(sysfs.energyFull);
        const energyDesign = formatEnergyWh(sysfs.energyFullDesign);

        this._batteryHealthItem.label.text = `Health: ${health}%`;
        this._batteryEnergyItem.label.text = `Energy: ${energyFull} / ${energyDesign}`;

        if (!withEc) {
            if (!this._batteryEcLoaded) {
                this._batteryLimitItem.label.text = 'Charge Limit: …';
                this._batteryModeItem.label.text = 'Power Mode: …';
            }
            return;
        }

        const payload = this._runBatteryProbe();
        if (!payload) {
            this._batteryBackendAvailable = false;
            this._batteryLimitItem.label.text = 'Charge Limit: backend unavailable';
            this._batteryModeItem.label.text = 'Power Mode: backend unavailable';
            this._buildBatteryMenus();
            return;
        }

        const chargeLimit = payload.charge_limit_percent;
        const powerMode = payload.power_supply_mode?.name || payload.power_supply_mode?.value;
        this._batteryEcLoaded = true;
        this._batteryBackendAvailable = true;

        this._batteryHealthItem.label.text = `Health: ${health}%`;
        this._batteryEnergyItem.label.text = `Energy: ${energyFull} / ${energyDesign}`;
        this._batteryLimitItem.label.text = `Charge Limit: ${chargeLimit ?? 'n/a'}%`;
        this._batteryModeItem.label.text = `Power Mode: ${powerMode ?? 'n/a'}`;
        this._buildBatteryMenus();
    }

    _spawn(argv, message) {
        try {
            Gio.Subprocess.new(argv, Gio.SubprocessFlags.NONE);
            this._statusItem.text = message;
        } catch (error) {
            log(`OXP control command error: ${error}`);
            this._statusItem.text = `Command failed: ${message}`;
        }
    }

    _runChecked(argv) {
        try {
            const proc = Gio.Subprocess.new(
                argv,
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE
            );
            const [, stdout, stderr] = proc.communicate_utf8(null, null);
            return {
                ok: proc.get_exit_status() === 0,
                stdout: stdout?.trim() || '',
                stderr: stderr?.trim() || '',
            };
        } catch (error) {
            return {
                ok: false,
                stdout: '',
                stderr: `${error}`,
            };
        }
    }

    _runLater(delayMs, callback) {
        return GLib.timeout_add(GLib.PRIORITY_DEFAULT, delayMs, () => {
            callback();
            return GLib.SOURCE_REMOVE;
        });
    }

    _applyCustomColor(rgb, saveAsCurrent = true, statusLabel = null) {
        const hex = rgbToHex(...rgb);
        if (saveAsCurrent) {
            this._config.lastColor = rgb;
            this._config.currentRgbState = {
                kind: 'custom',
                rgb,
                label: hex,
            };
            this._saveConfig();
            this._updateInfoRows();
        }

        this._spawn(
            [RGB_HID_HELPER, 'static', String(rgb[0]), String(rgb[1]), String(rgb[2])],
            statusLabel || `RGB color ${hex}`
        );
        this._runLater(180, () => {
            this._spawn([RGB_HID_HELPER, 'mode', 'alt-static'], statusLabel || `RGB color ${hex}`);
        });
    }

    _applyRgbState(state, statusLabel = null, save = true) {
        if (!state) {
            return;
        }

        if (state.kind === 'custom') {
            this._applyCustomColor(sanitizeRgb(state.rgb, DEFAULT_COLOR), save, statusLabel);
            return;
        }

        this._spawn([RGB_HELPER, state.preset], statusLabel || `RGB: ${rgbStateLabel(state)}`);
        if (save) {
            this._config.currentRgbState = {
                kind: 'preset',
                preset: state.preset,
                label: state.label || state.preset,
            };
            this._saveConfig();
            this._updateInfoRows();
        }
    }

    _setProfile(profileName) {
        this._spawn(['pkexec', PROFILE_HELPER, 'set', profileName], `Switching to ${profileName}…`);
        GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 2, () => {
            this._refresh();
            return GLib.SOURCE_REMOVE;
        });
    }

    _setTdp(watts) {
        const power = this._readPowerSourceInfo();
        if (power.onBattery && watts > MAX_BATTERY_TDP_WATTS) {
            this._statusItem.text = `Battery mode limit: ${MAX_BATTERY_TDP_WATTS}W max`;
            return;
        }
        this._spawn(['pkexec', TDP_HELPER, String(watts)], `TDP ${watts}W`);
        this._config.currentTdpWatts = watts;
        this._saveConfig();
        this._buildTdpMenu();
        this._updateInfoRows();
    }

    _enforceBatteryTdpSafety() {
        const power = this._readPowerSourceInfo();
        const onBattery = power.onBattery;

        if (this._lastOnBattery === undefined) {
            this._lastOnBattery = onBattery;
        }

        if (onBattery && !this._lastOnBattery && this._config.currentTdpWatts > SAFE_BATTERY_TDP_WATTS) {
            this._statusItem.text = `On battery: falling back to ${SAFE_BATTERY_TDP_WATTS}W`;
            this._setTdp(SAFE_BATTERY_TDP_WATTS);
        }

        if (onBattery && this._config.currentTdpWatts > MAX_BATTERY_TDP_WATTS) {
            this._statusItem.text = `Battery mode limit: forcing ${SAFE_BATTERY_TDP_WATTS}W`;
            this._setTdp(SAFE_BATTERY_TDP_WATTS);
        }

        this._lastOnBattery = onBattery;
        return power;
    }

    _setChargeLimit(percent) {
        const result = this._runChecked([BATTERY_EC_HELPER, 'set-charge-limit', String(percent)]);
        if (!result.ok) {
            this._statusItem.text = `Charge limit failed: ${result.stderr || 'backend unavailable'}`;
            this._refreshBatteryInfo(true);
            return;
        }
        this._statusItem.text = `Charge limit ${percent}%`;
        this._refreshBatteryInfo(true);
    }

    _setBypassMode(mode, label) {
        const result = this._runChecked([BATTERY_EC_HELPER, 'set-bypass-mode', mode]);
        if (!result.ok) {
            this._statusItem.text = `Bypass failed: ${result.stderr || 'backend unavailable'}`;
            this._refreshBatteryInfo(true);
            return;
        }
        this._statusItem.text = `Bypass ${label}`;
        this._refreshBatteryInfo(true);
    }

    _confirmHighTdp(watts) {
        try {
            const proc = Gio.Subprocess.new(
                [
                    '/usr/bin/zenity',
                    '--question',
                    '--width=420',
                    '--title=High TDP Warning',
                    `--text=Applying ${watts} W requires water cooling. Continue?`,
                ],
                Gio.SubprocessFlags.NONE
            );
            proc.wait_check_async(null, (self, res) => {
                try {
                    if (self.wait_check_finish(res)) {
                        this._setTdp(watts);
                    }
                } catch (_error) {
                }
            });
        } catch (error) {
            log(`OXP TDP warning dialog error: ${error}`);
            this._statusItem.text = 'Unable to show TDP warning';
        }
    }

    _applyPreset(action) {
        this._applyRgbState(
            {
                kind: 'preset',
                preset: action.preset,
                label: action.label,
            },
            `RGB: ${action.label}`,
            true
        );
    }

    _pickColor(initialColor, title, onColor) {
        try {
            const proc = Gio.Subprocess.new(
                [
                    '/usr/bin/zenity',
                    '--color-selection',
                    '--show-palette',
                    `--color=${initialColor}`,
                    `--title=${title}`,
                ],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE
            );
            proc.communicate_utf8_async(null, null, (self, res) => {
                try {
                    const [, stdout] = self.communicate_utf8_finish(res);
                    if (self.get_exit_status() !== 0) {
                        return;
                    }
                    const rgb = parseColorOutput(stdout);
                    if (!rgb) {
                        this._statusItem.text = 'Color picker returned an unknown format';
                        return;
                    }
                    onColor(rgb);
                } catch (error) {
                    log(`OXP color picker error: ${error}`);
                    this._statusItem.text = 'Color picker failed';
                }
            });
        } catch (error) {
            log(`OXP color picker launch error: ${error}`);
            this._statusItem.text = 'Unable to launch color picker';
        }
    }

    _openMainColorPicker() {
        const initialColor = rgbToHex(...this._config.lastColor);
        this._pickColor(initialColor, 'Choose OneXPlayer Super X RGB Color', rgb => {
            this._applyCustomColor(rgb, true);
        });
    }

    _openNotificationColorPicker() {
        const initialColor = rgbToHex(...this._config.notificationColor);
        this._pickColor(initialColor, 'Choose Notification Flash Color', rgb => {
            this._config.notificationColor = rgb;
            this._saveConfig();
            this._updateInfoRows();
            this._statusItem.text = `Notify color ${rgbToHex(...rgb)}`;
        });
    }

    _flashNotificationColor() {
        const previousState = this._config.currentRgbState;
        const flashHex = rgbToHex(...this._config.notificationColor);

        if (this._notificationFlashTimeoutId) {
            GLib.Source.remove(this._notificationFlashTimeoutId);
            this._notificationFlashTimeoutId = null;
        }
        for (const id of this._notificationFlashStepIds) {
            GLib.Source.remove(id);
        }
        this._notificationFlashStepIds = [];

        const offState = {
            kind: 'preset',
            preset: 'off',
            label: 'Off',
        };
        const flashState = {
            kind: 'custom',
            rgb: this._config.notificationColor,
            label: flashHex,
        };
        const steps = [
            {delay: 0, state: offState},
            {delay: NOTIFICATION_FLASH_PATTERN_MS, state: flashState},
            {delay: NOTIFICATION_FLASH_PATTERN_MS * 2, state: offState},
            {delay: NOTIFICATION_FLASH_PATTERN_MS * 3, state: flashState},
        ];

        for (const step of steps) {
            const id = this._runLater(step.delay, () => {
                this._applyRgbState(step.state, `Notify flash ${flashHex}`, false);
            });
            this._notificationFlashStepIds.push(id);
        }

        this._notificationFlashTimeoutId = this._runLater(NOTIFICATION_FLASH_PATTERN_MS * 4 + 140, () => {
            this._notificationFlashTimeoutId = null;
            this._notificationFlashStepIds = [];
            this._applyRgbState(previousState, `RGB: ${rgbStateLabel(previousState)}`, false);
            this._updateInfoRows();
        });
    }

    _onNotificationAdded(_source, notification) {
        if (!notification || !this._config.notificationFlashEnabled) {
            return;
        }
        if (notification.urgency === 0 && notification.resident) {
            return;
        }
        this._flashNotificationColor();
    }

    _connectNotificationSource(source) {
        if (!source || this._notificationSourceSignals.has(source)) {
            return;
        }
        const signalId = source.connect('notification-added', this._onNotificationAdded.bind(this));
        this._notificationSourceSignals.set(source, signalId);
        source.connect('destroy', () => {
            if (this._notificationSourceSignals.has(source)) {
                this._notificationSourceSignals.delete(source);
            }
        });
    }

    _connectNotificationSignals() {
        if (Main.messageTray && Main.messageTray.getSources) {
            for (const source of Main.messageTray.getSources()) {
                this._connectNotificationSource(source);
            }
        }

        if (Main.messageTray) {
            this._messageTraySignals.push(
                Main.messageTray.connect('source-added', (_tray, source) => {
                    this._connectNotificationSource(source);
                })
            );
        }
    }

    _buildActionSection(section, actions) {
        section.removeAll();
        for (const action of actions) {
            const item = new PopupMenu.PopupMenuItem(action.label);
            item.connect('activate', () => {
                if (action.kind === 'picker') {
                    this._openMainColorPicker();
                    return;
                }
                if (action.kind === 'last-custom') {
                    this._applyCustomColor(this._config.lastColor, true);
                    return;
                }
                this._applyPreset(action);
            });
            section.addMenuItem(item);
        }
    }

    _buildRgbMenu() {
        this._buildActionSection(this._quickColorsSection, QUICK_COLORS);
        this._quickColorsSection.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        for (const action of BRIGHTNESS_ACTIONS) {
            const item = new PopupMenu.PopupMenuItem(action.label);
            item.connect('activate', () => this._applyPreset(action));
            this._quickColorsSection.addMenuItem(item);
        }
        this._buildActionSection(this._effectsSection, EFFECT_ACTIONS);
        this._buildActionSection(this._monoSection, MONO_ACTIONS);
    }

    _buildBatteryMenus() {
        this._batteryChargeMenu.menu.removeAll();
        this._batteryBypassMenu.menu.removeAll();

        if (this._batteryBackendAvailable === false) {
            this._batteryChargeMenu.label.text = 'Charge Limit (unavailable)';
            this._batteryBypassMenu.label.text = 'Bypass Mode (unavailable)';

            const chargeInfo = new PopupMenu.PopupMenuItem('Battery write backend unavailable', {
                reactive: false,
                can_focus: false,
            });
            const bypassInfo = new PopupMenu.PopupMenuItem('Battery write backend unavailable', {
                reactive: false,
                can_focus: false,
            });
            this._batteryChargeMenu.menu.addMenuItem(chargeInfo);
            this._batteryBypassMenu.menu.addMenuItem(bypassInfo);
            return;
        }

        this._batteryChargeMenu.label.text = 'Charge Limit';
        for (const percent of CHARGE_LIMIT_ACTIONS) {
            const item = new PopupMenu.PopupMenuItem(`${percent}%`);
            item.connect('activate', () => this._setChargeLimit(percent));
            this._batteryChargeMenu.menu.addMenuItem(item);
        }

        this._batteryBypassMenu.label.text = 'Bypass Mode';
        for (const action of BYPASS_ACTIONS) {
            const item = new PopupMenu.PopupMenuItem(action.label);
            item.connect('activate', () => this._setBypassMode(action.value, action.label));
            this._batteryBypassMenu.menu.addMenuItem(item);
        }
    }

    _buildTdpMenu() {
        const power = this._readPowerSourceInfo();
        this._tdpMenu.menu.removeAll();
        for (const watts of TDP_ACTIONS) {
            const batteryBlocked = power.onBattery && watts > MAX_BATTERY_TDP_WATTS;
            const suffix = batteryBlocked ? ' (AC only)' : '';
            const item = new PopupMenu.PopupMenuItem(`${watts} W${suffix}`);
            if (watts === this._config.currentTdpWatts) {
                item.setOrnament(PopupMenu.Ornament.DOT);
            }
            item.connect('activate', () => {
                if (batteryBlocked) {
                    this._statusItem.text = `Battery mode limit: ${MAX_BATTERY_TDP_WATTS}W max`;
                    return;
                }
                if (watts > TDP_WARNING_WATTS) {
                    this._confirmHighTdp(watts);
                    return;
                }
                this._setTdp(watts);
            });
            this._tdpMenu.menu.addMenuItem(item);
        }
    }

    _refresh() {
        const status = this._runStatus();
        this._enforceBatteryTdpSafety();
        this._profilesMenu.menu.removeAll();
        this._buildTdpMenu();
        this._refreshBatteryInfo(false);

        if (!status || !status.profiles || status.profiles.length === 0) {
            this._currentFanProfile = null;
            this._updateInfoRows();
            return;
        }

        this._currentFanProfile = status.current;
        this._updateInfoRows();

        for (const profile of status.profiles) {
            const item = new PopupMenu.PopupMenuItem(profile);
            if (profile === status.current) {
                item.setOrnament(PopupMenu.Ornament.DOT);
            }
            item.connect('activate', () => this._setProfile(profile));
            this._profilesMenu.menu.addMenuItem(item);
        }
    }

    destroy() {
        if (this._notificationFlashTimeoutId) {
            GLib.Source.remove(this._notificationFlashTimeoutId);
            this._notificationFlashTimeoutId = null;
        }
        for (const id of this._notificationFlashStepIds) {
            GLib.Source.remove(id);
        }
        this._notificationFlashStepIds = [];
        if (this._timeoutId) {
            GLib.Source.remove(this._timeoutId);
            this._timeoutId = null;
        }
        for (const [source, signalId] of this._notificationSourceSignals.entries()) {
            if (signalId) {
                source.disconnect(signalId);
            }
        }
        this._notificationSourceSignals.clear();
        if (this._upowerProxy && this._upowerSignalId) {
            this._upowerProxy.disconnect(this._upowerSignalId);
            this._upowerSignalId = 0;
        }
        this._upowerProxy = null;
        if (Main.messageTray) {
            for (const signalId of this._messageTraySignals) {
                Main.messageTray.disconnect(signalId);
            }
        }
        this._messageTraySignals = [];
        super.destroy();
    }
});

export default class OXPFanProfilesExtension extends Extension {
    enable() {
        this._button = new OXPFanProfilesButton();
        Main.panel.addToStatusArea('oxp-fan-profiles', this._button, 0, 'right');
    }

    disable() {
        if (this._button) {
            this._button.destroy();
            this._button = null;
        }
    }
}
