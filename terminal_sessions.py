"""Select an existing Konsole conversation tab; never send text to its shell."""
from pathlib import Path
import re
import shutil
import subprocess


def terminal_for_pid(pid, proc='/proc'):
    """Read only Konsole routing variables, keeping process environments private."""
    if not isinstance(pid, int) or pid <= 1:
        return None
    try:
        values = {}
        for item in (Path(proc) / str(pid) / 'environ').read_bytes().split(b'\0'):
            key, _, value = item.partition(b'=')
            if key in (b'TMUX', b'TMUX_PANE', b'STY') and value:
                return None  # inherited Konsole variables cannot identify a multiplexer pane
            if key in (b'KONSOLE_DBUS_SERVICE', b'KONSOLE_DBUS_SESSION'):
                values[key.decode()] = value.decode(errors='replace')
    except OSError:
        return None
    service = values.get('KONSOLE_DBUS_SERVICE', '')
    session = values.get('KONSOLE_DBUS_SESSION', '')
    if (re.fullmatch(r'(?:org\.kde\.konsole-\d+|:\d+\.\d+)', service)
            and re.fullmatch(r'/Sessions/[1-9]\d*', session)):
        return {'kind': 'konsole', 'service': service, 'session': session, 'pid': pid}
    return None


def qdbus(executable, *args):
    result = subprocess.run([executable, *args], capture_output=True, text=True, timeout=2, check=True)
    return result.stdout.strip()


def focus_terminal(target, run=qdbus, which=shutil.which, verify=terminal_for_pid):
    if not isinstance(target, dict) or target.get('kind') != 'konsole':
        return False, 'No exact terminal tab is known for this session.'
    if verify(target.get('pid')) != target:
        return False, 'That agent terminal has closed or changed.'
    executable = which('qdbus6') or which('qdbus')
    if not executable:
        return False, 'Konsole tab switching needs qdbus6 or qdbus.'
    service, session = target['service'], target['session']
    session_id = session.rsplit('/', 1)[-1]
    try:
        paths = run(executable, service).splitlines()
        windows = [path for path in paths if re.fullmatch(r'/Windows/[1-9]\d*', path)]
        for window in windows:
            sessions = run(executable, service, window, 'org.kde.konsole.Window.sessionList').splitlines()
            if session_id not in sessions:
                continue
            run(executable, service, window, 'org.kde.konsole.Window.setCurrentSession', session_id)
            try:
                widgets = [path for path in paths if re.fullmatch(r'/konsole/MainWindow_\d+', path)]
                # Qt window names and Konsole's window IDs have separate counters.
                # Only raise an unambiguous widget, using its selected tab title.
                if len(widgets) > 1:
                    title = run(executable, service, session, 'org.kde.konsole.Session.title', '1')
                    widgets = [widget for widget in widgets if title and run(
                        executable, service, widget, 'org.qtproject.Qt.QWidget.windowTitle') == title]
                if len(widgets) != 1:
                    return True, 'Tab selected; bring its Konsole window to the front.'
                widget = widgets[0]
                # Restore only minimized windows, keeping maximized/full-screen layouts.
                if run(executable, service, widget, 'org.qtproject.Qt.QWidget.minimized') == 'true':
                    run(executable, service, widget, 'org.qtproject.Qt.QWidget.showNormal')
                run(executable, service, widget, 'org.qtproject.Qt.QWidget.raise')
            except (OSError, subprocess.SubprocessError):
                return True, 'Tab selected; bring its Konsole window to the front.'
            return True, 'Conversation tab selected.'
    except (OSError, subprocess.SubprocessError):
        return False, 'Konsole could not select that conversation tab.'
    return False, 'That conversation tab is no longer in Konsole.'
