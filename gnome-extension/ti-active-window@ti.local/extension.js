import Clutter from 'gi://Clutter';
import GLib from 'gi://GLib';
import Gio from 'gi://Gio';
import GObject from 'gi://GObject';
import St from 'gi://St';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

const STALE_SECONDS = 20;   // daemon silent for this long => hide all TI UI
const SNOOZE_MS = 90_000;   // "I'm back" hides the overlay for this long
const INFO_BANNER_SECONDS = 6;

const TIIndicator = GObject.registerClass(
class TIIndicator extends PanelMenu.Button {
    _init() {
        super._init(0.5, 'TI', false);
        this._pill = new St.Label({
            text: 'TI',
            y_align: Clutter.ActorAlign.CENTER,
            style_class: 'ti-pill ti-pill-idle',
        });
        this.add_child(this._pill);
        this._lines = [0, 1].map(() => {
            const item = new PopupMenu.PopupMenuItem('', {reactive: false});
            this.menu.addMenuItem(item);
            return item;
        });
    }

    update(cls, text, line1, line2) {
        this._pill.style_class = `ti-pill ${cls}`;
        this._pill.text = text;
        this._lines[0].label.text = line1;
        this._lines[1].label.text = line2;
    }
});

export default class TI extends Extension {
    enable() {
        this._enableActiveWindow();

        this._indicator = new TIIndicator();
        Main.panel.addToStatusArea('ti-indicator', this._indicator, 0, 'right');

        this._banner = null;
        this._bannerTimeout = 0;
        this._overlay = null;
        this._snoozeUntil = 0;
        this._lastKey = undefined;
        this._stateFile = Gio.File.new_for_path(GLib.build_filenamev(
            [GLib.get_user_runtime_dir(), 'ti', 'state.json']));

        this._tick();
        this._pollId = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 1, () => {
            this._tick();
            return GLib.SOURCE_CONTINUE;
        });
    }

    disable() {
        if (this._pollId) {
            GLib.source_remove(this._pollId);
            this._pollId = 0;
        }
        this._clearBannerTimeout();
        this._destroyBanner();
        this._destroyOverlay();
        this._indicator?.destroy();
        this._indicator = null;
        this._stateFile = null;
        this._disableActiveWindow();
    }

    // ---- state ---------------------------------------------------------

    _readState() {
        try {
            const [ok, bytes] = this._stateFile.load_contents(null);
            if (!ok)
                return null;
            const s = JSON.parse(new TextDecoder().decode(bytes));
            if (Date.now() / 1000 - s.ts > STALE_SECONDS)
                return null;
            return s;
        } catch (_e) {
            return null;
        }
    }

    _minutesLeft(block) {
        const [h, m] = block.end.split(':').map(Number);
        const now = new Date();
        return h * 60 + m - (now.getHours() * 60 + now.getMinutes());
    }

    _tick() {
        const s = this._readState();
        if (!s) {
            this._indicator.update('ti-pill-idle', 'TI', 'TI is offline', 'Run: ti.py watch');
            this._hideBanner();
            this._hideOverlay();
            this._lastKey = undefined;
            return;
        }

        const block = s.block;
        const key = block ? `${block.start}|${block.title}` : 'none';
        const announce = this._lastKey !== undefined && key !== this._lastKey;
        this._lastKey = key;

        this._updateIndicator(s);

        if (s.state === 'off' && s.level >= 3 && Date.now() >= this._snoozeUntil) {
            this._hideBanner();
            this._showOverlay(s);
            return;
        }
        this._hideOverlay();

        if (s.state === 'off' && s.level >= 1) {
            const l = Math.min(s.level, 2);
            this._showBanner(`ti-banner-l${l}`, 'OFF THE LINE',
                `${s.app} isn't part of "${block.title}". Get back to it.`, false);
        } else if (announce) {
            this._clearBannerTimeout();
            if (block) {
                this._showBanner('ti-banner-info', block.type === 'focus' ? 'NEW STRETCH' : 'NEXT UP',
                    `${block.title} until ${block.end}`, true);
            } else {
                this._showBanner('ti-banner-info', 'CLEAR TRACK', 'Nothing scheduled right now.', true);
            }
        } else if (this._bannerKind === 'drift') {
            this._hideBanner();
        }
    }

    _updateIndicator(s) {
        const b = s.block;
        if (!b) {
            const nxt = s.next ? `Next: ${s.next.start} ${s.next.title}` : 'Nothing else today';
            this._indicator.update('ti-pill-idle', 'TI', 'No block right now', nxt);
            return;
        }
        let cls = 'ti-pill-idle';
        if (s.state === 'off')
            cls = 'ti-pill-off';
        else if (b.type === 'focus')
            cls = 'ti-pill-on';
        else if (b.type === 'break')
            cls = 'ti-pill-break';
        const left = this._minutesLeft(b);
        const text = `TI · ${b.title} · ${left}m`;
        const line2 = s.state === 'off' ? `Off the line: ${s.app}` : (s.next ? `Next: ${s.next.start} ${s.next.title}` : 'Last block of the day');
        this._indicator.update(cls, text, `[${b.type}] ${b.title} until ${b.end}`, line2);
    }

    // ---- banner --------------------------------------------------------

    _clearBannerTimeout() {
        if (this._bannerTimeout) {
            GLib.source_remove(this._bannerTimeout);
            this._bannerTimeout = 0;
        }
    }

    _showBanner(cls, title, sub, autoHide) {
        if (!this._banner) {
            const monitor = Main.layoutManager.primaryMonitor;
            this._bannerBox = new St.BoxLayout({style_class: 'ti-banner', vertical: false});
            this._bannerBadge = new St.Label({text: 'TI', style_class: 'ti-badge', y_align: Clutter.ActorAlign.CENTER});
            const col = new St.BoxLayout({vertical: true, y_align: Clutter.ActorAlign.CENTER});
            this._bannerTitle = new St.Label({style_class: 'ti-banner-title'});
            this._bannerSub = new St.Label({style_class: 'ti-banner-sub'});
            col.add_child(this._bannerTitle);
            col.add_child(this._bannerSub);
            this._bannerBox.add_child(this._bannerBadge);
            this._bannerBox.add_child(col);

            // Full-width, click-through row that centres the banner on the primary monitor.
            this._banner = new St.BoxLayout({width: monitor.width, reactive: false});
            this._bannerBox.x_expand = true;
            this._bannerBox.x_align = Clutter.ActorAlign.CENTER;
            this._banner.add_child(this._bannerBox);
            this._banner.set_position(monitor.x, monitor.y + 70);
            this._banner.opacity = 0;
            Main.layoutManager.addTopChrome(this._banner);
            this._banner.ease({opacity: 255, duration: 250, mode: Clutter.AnimationMode.EASE_OUT_QUAD});
        }
        this._bannerBox.style_class = `ti-banner ${cls}`;
        this._bannerTitle.text = title;
        this._bannerSub.text = sub;
        this._bannerKind = autoHide ? 'info' : 'drift';
        this._clearBannerTimeout();
        if (autoHide) {
            this._bannerTimeout = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, INFO_BANNER_SECONDS, () => {
                this._bannerTimeout = 0;
                this._hideBanner();
                return GLib.SOURCE_REMOVE;
            });
        }
    }

    _hideBanner() {
        if (!this._banner || this._bannerKind === 'info' && this._bannerTimeout)
            return;
        const banner = this._banner;
        this._banner = null;
        this._bannerKind = null;
        banner.ease({
            opacity: 0, duration: 200, mode: Clutter.AnimationMode.EASE_IN_QUAD,
            onComplete: () => banner.destroy(),
        });
    }

    _destroyBanner() {
        this._banner?.destroy();
        this._banner = null;
        this._bannerKind = null;
    }

    // ---- overlay -------------------------------------------------------

    _showOverlay(s) {
        const driftSecs = Math.max(0, Math.floor(Date.now() / 1000 - s.drift_since));
        const timer = `${Math.floor(driftSecs / 60)}:${String(driftSecs % 60).padStart(2, '0')}`;
        if (!this._overlay) {
            const monitor = Main.layoutManager.primaryMonitor;
            this._overlay = new St.BoxLayout({
                style_class: 'ti-overlay', vertical: true, reactive: true,
                x: monitor.x, y: monitor.y, width: monitor.width, height: monitor.height,
            });
            const centre = {x_align: Clutter.ActorAlign.CENTER};
            const mk = (text, cls) => new St.Label({text, style_class: cls, ...centre});

            this._overlay.add_child(new St.Widget({style_class: 'ti-stripe', x_expand: true}));
            this._overlay.add_child(new St.Widget({y_expand: true}));
            this._overlay.add_child(mk('TI', 'ti-overlay-badge'));
            this._overlay.add_child(mk('TRAJECTOIRE IDÉALE', 'ti-overlay-brand'));
            this._ovHead = mk('BACK TO THE LINE', 'ti-overlay-head');
            this._ovSub = mk('', 'ti-overlay-sub');
            this._ovTimer = mk('', 'ti-overlay-timer');
            this._overlay.add_child(this._ovHead);
            this._overlay.add_child(this._ovSub);
            this._overlay.add_child(this._ovTimer);

            const btn = new St.Button({label: "I'M BACK", style_class: 'ti-overlay-btn', reactive: true, can_focus: true, ...centre});
            btn.connect('clicked', () => {
                this._snoozeUntil = Date.now() + SNOOZE_MS;
                this._hideOverlay();
            });
            this._overlay.add_child(btn);
            this._overlay.add_child(new St.Widget({y_expand: true}));
            this._overlay.add_child(new St.Widget({style_class: 'ti-stripe', x_expand: true}));

            this._overlay.opacity = 0;
            Main.layoutManager.addTopChrome(this._overlay);
            this._overlay.ease({opacity: 255, duration: 300, mode: Clutter.AnimationMode.EASE_OUT_QUAD});
        }
        this._ovSub.text = `${s.app} is not part of "${s.block.title}" (until ${s.block.end}).`;
        this._ovTimer.text = `OFF THE LINE  ${timer}`;
    }

    _hideOverlay() {
        if (!this._overlay)
            return;
        const overlay = this._overlay;
        this._overlay = null;
        overlay.ease({
            opacity: 0, duration: 200, mode: Clutter.AnimationMode.EASE_IN_QUAD,
            onComplete: () => overlay.destroy(),
        });
    }

    _destroyOverlay() {
        this._overlay?.destroy();
        this._overlay = null;
    }

    // ---- active window (feeds the daemon) ------------------------------

    _enableActiveWindow() {
        const dir = GLib.build_filenamev([GLib.get_user_runtime_dir(), 'ti']);
        GLib.mkdir_with_parents(dir, 0o700);
        this._file = Gio.File.new_for_path(GLib.build_filenamev([dir, 'active.json']));
        this._window = null;
        this._titleId = 0;
        this._focusId = global.display.connect('notify::focus-window', () => this._onFocus());
        this._onFocus();
    }

    _disableActiveWindow() {
        global.display.disconnect(this._focusId);
        this._detachTitle();
        this._file = null;
    }

    _detachTitle() {
        if (this._window && this._titleId)
            this._window.disconnect(this._titleId);
        this._window = null;
        this._titleId = 0;
    }

    _onFocus() {
        this._detachTitle();
        this._window = global.display.focus_window;
        if (this._window)
            this._titleId = this._window.connect('notify::title', () => this._write());
        this._write();
    }

    _write() {
        const w = this._window;
        const data = {
            app: w ? (w.get_wm_class() ?? '') : '',
            title: w ? (w.get_title() ?? '') : '',
            ts: Math.floor(Date.now() / 1000),
        };
        this._file.replace_contents(
            new TextEncoder().encode(JSON.stringify(data)),
            null, false, Gio.FileCreateFlags.REPLACE_DESTINATION, null);
    }
}
