import Adw from 'gi://Adw';
import Gio from 'gi://Gio';
import Gtk from 'gi://Gtk';

import {ExtensionPreferences} from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';


const TURBO_HELPER = '/usr/local/bin/oxp-turbo-tdp';
const PROFILE_VALUES = [
    'power-saver', 'balanced', 'performance', 'adaptive', 'ultra', 'unchanged',
];
const PROFILE_LABELS = [
    'Power Saver', 'Balanced', 'Performance', 'Adaptive', 'Ultra Saver', 'Unchanged',
];
const LED_VALUES = [
    'unchanged', 'off', 'dim', 'mid', 'bright', 'rainbow', 'red', 'green', 'blue',
    'warm', 'rainbow-flow', 'rainbow-breath-random', 'rainbow-cycle',
    'slow-color-runner', 'slow-color-breath', 'slow-color-breath-2',
    'slow-color-breath-3', 'flame-cycle', 'cyberpunk', 'teal-green-drops',
    'pink-red-drops', 'whole-rainbow-cycle', 'red-monster', 'green-monster',
    'blue-monster', 'green-breath', 'cyan-breath', 'pink-breath',
    'white-breath-slow', 'red-solid',
];

const DEFAULT_CONFIG = {
    behavior: 'toggle',
    firmware_action: true,
    command: '',
    initial_state: 'power-saving',
    states: [
        {
            name: 'power-saving',
            power_profile: 'power-saver',
            tdp: [10, 15, 10],
            led: 'unchanged',
            command: '',
        },
        {
            name: 'performance',
            power_profile: 'performance',
            tdp: [80, 80, 80],
            led: 'unchanged',
            command: '',
        },
    ],
};


function titleCase(value) {
    return value.split('-').map(word => word.charAt(0).toUpperCase() + word.slice(1)).join(' ');
}

function selectedIndex(values, value, fallback = 0) {
    const index = values.indexOf(value);
    return index >= 0 ? index : fallback;
}

function runHelper(argv) {
    const process = Gio.Subprocess.new(
        argv,
        Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE
    );
    const [, stdout, stderr] = process.communicate_utf8(null, null);
    if (process.get_exit_status() !== 0) {
        throw new Error(stderr.trim() || stdout.trim() || 'Turbo helper failed');
    }
    return stdout.trim();
}

function comboRow(title, labels) {
    return new Adw.ComboRow({
        title,
        model: Gtk.StringList.new(labels),
    });
}

function spinRow(title, value) {
    const row = Adw.SpinRow.new_with_range(3, 80, 1);
    row.title = title;
    row.value = value;
    return row;
}


export default class OXPPreferences extends ExtensionPreferences {
    fillPreferencesWindow(window) {
        this._window = window;
        window.set_default_size(720, 760);
        window.set_search_enabled(true);

        const page = new Adw.PreferencesPage({
            title: 'Turbo Button',
            icon_name: 'preferences-system-symbolic',
        });
        window.add(page);

        this._behaviorGroup = new Adw.PreferencesGroup({
            title: 'Button Behavior',
            description: 'Choose whether Turbo toggles two configured states or runs one command.',
        });
        page.add(this._behaviorGroup);

        this._behaviorRow = comboRow('Action', ['Toggle Two Modes', 'Run Custom Command']);
        this._behaviorGroup.add(this._behaviorRow);

        this._firmwareRow = new Adw.SwitchRow({
            title: 'Keep Factory Turbo Action',
            subtitle: 'Preserve the firmware TDP and factory Turbo LED action before running yours.',
        });
        this._behaviorGroup.add(this._firmwareRow);

        this._initialRow = comboRow('Initial State', ['State 1', 'State 2']);
        this._behaviorGroup.add(this._initialRow);

        this._commandGroup = new Adw.PreferencesGroup({
            title: 'Custom Command',
            description: 'Runs as root when the button is pressed.',
        });
        page.add(this._commandGroup);
        this._commandRow = new Adw.EntryRow({title: 'Command'});
        this._commandGroup.add(this._commandRow);

        this._stateWidgets = [
            this._createStateGroup(page, 'State 1'),
            this._createStateGroup(page, 'State 2'),
        ];

        const saveGroup = new Adw.PreferencesGroup();
        page.add(saveGroup);
        const saveRow = new Adw.ActionRow({
            title: 'Apply Turbo Button Configuration',
            subtitle: 'Administrator authorization is required. The Turbo service restarts automatically.',
        });
        this._saveButton = new Gtk.Button({
            label: 'Save',
            valign: Gtk.Align.CENTER,
            css_classes: ['suggested-action'],
        });
        this._saveButton.connect('clicked', () => this._save());
        saveRow.add_suffix(this._saveButton);
        saveRow.activatable_widget = this._saveButton;
        saveGroup.add(saveRow);

        this._behaviorRow.connect('notify::selected', () => this._updateVisibility());
        this._load();
    }

    _createStateGroup(page, title) {
        const group = new Adw.PreferencesGroup({
            title,
            description: 'The optional command runs after profile, TDP, and LED changes.',
        });
        page.add(group);

        const name = new Adw.EntryRow({title: 'State Name'});
        group.add(name);

        const profile = comboRow('CPU Power Profile', PROFILE_LABELS);
        group.add(profile);

        const applyTdp = new Adw.SwitchRow({
            title: 'Apply TDP Limits',
            subtitle: 'Configure STAPM, fast, and slow limits independently.',
        });
        group.add(applyTdp);

        const stapm = spinRow('STAPM Limit (W)', 10);
        const fast = spinRow('Fast Limit (W)', 15);
        const slow = spinRow('Slow Limit (W)', 10);
        group.add(stapm);
        group.add(fast);
        group.add(slow);

        const led = comboRow('LED Preset', LED_VALUES.map(titleCase));
        group.add(led);

        const command = new Adw.EntryRow({title: 'Command After Toggle'});
        group.add(command);

        applyTdp.connect('notify::active', () => {
            stapm.visible = applyTdp.active;
            fast.visible = applyTdp.active;
            slow.visible = applyTdp.active;
        });

        return {group, name, profile, applyTdp, stapm, fast, slow, led, command};
    }

    _load() {
        let config = DEFAULT_CONFIG;
        try {
            const output = runHelper([TURBO_HELPER, '--print-config-json']);
            config = JSON.parse(output);
            if (!Array.isArray(config.states) || config.states.length !== 2) {
                config.states = DEFAULT_CONFIG.states;
                config.initial_state = DEFAULT_CONFIG.initial_state;
            }
        } catch (error) {
            this._toast(`Could not load system configuration: ${error.message}`);
        }

        this._behaviorRow.selected = config.behavior === 'command' ? 1 : 0;
        this._firmwareRow.active = Boolean(config.firmware_action);
        this._commandRow.text = config.command || '';
        this._initialRow.selected = config.initial_state === config.states[1].name ? 1 : 0;

        for (let index = 0; index < 2; index++) {
            const state = config.states[index];
            const widgets = this._stateWidgets[index];
            widgets.name.text = state.name;
            widgets.profile.selected = selectedIndex(PROFILE_VALUES, state.power_profile);
            widgets.applyTdp.active = Array.isArray(state.tdp);
            const tdp = Array.isArray(state.tdp) ? state.tdp : [10, 15, 10];
            widgets.stapm.value = tdp[0];
            widgets.fast.value = tdp[1];
            widgets.slow.value = tdp[2];
            widgets.led.selected = selectedIndex(LED_VALUES, state.led);
            widgets.command.text = state.command || '';
        }
        this._updateVisibility();
    }

    _updateVisibility() {
        const toggle = this._behaviorRow.selected === 0;
        this._initialRow.visible = toggle;
        this._commandGroup.visible = !toggle;
        for (const widgets of this._stateWidgets) {
            widgets.group.visible = toggle;
            widgets.stapm.visible = widgets.applyTdp.active;
            widgets.fast.visible = widgets.applyTdp.active;
            widgets.slow.visible = widgets.applyTdp.active;
        }
    }

    _payload() {
        const states = this._stateWidgets.map(widgets => ({
            name: widgets.name.text.trim(),
            power_profile: PROFILE_VALUES[widgets.profile.selected],
            tdp: widgets.applyTdp.active
                ? [widgets.stapm.value, widgets.fast.value, widgets.slow.value]
                : null,
            led: LED_VALUES[widgets.led.selected],
            command: widgets.command.text.trim(),
        }));
        return {
            behavior: this._behaviorRow.selected === 0 ? 'toggle' : 'command',
            firmware_action: this._firmwareRow.active,
            command: this._commandRow.text.trim(),
            initial_state: states[this._initialRow.selected].name,
            states,
        };
    }

    _save() {
        const payload = JSON.stringify(this._payload());
        this._saveButton.sensitive = false;
        let process;
        try {
            process = Gio.Subprocess.new(
                ['pkexec', TURBO_HELPER, '--write-config-json', payload],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE
            );
        } catch (error) {
            this._saveButton.sensitive = true;
            this._toast(`Could not start settings helper: ${error.message}`);
            return;
        }

        process.communicate_utf8_async(null, null, (source, result) => {
            this._saveButton.sensitive = true;
            try {
                const [, stdout, stderr] = source.communicate_utf8_finish(result);
                if (source.get_exit_status() !== 0) {
                    throw new Error(stderr.trim() || stdout.trim() || 'Save failed');
                }
                this._toast('Turbo button settings saved');
            } catch (error) {
                this._toast(`Could not save settings: ${error.message}`);
            }
        });
    }

    _toast(message) {
        this._window.add_toast(new Adw.Toast({title: message, timeout: 5}));
    }
}
