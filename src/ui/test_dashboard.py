import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.core.config_manager import ConfigManager
import PySimpleGUI as sg

def create_simple_dashboard():
    """Create a simple dashboard without matplotlib graphs."""
    sg.theme('DarkGrey14')
    
    layout = [
        [sg.Text('VIGIL - Simple Dashboard', font=('Helvetica', 20, 'bold'))],
        [sg.HorizontalSeparator()],
        [sg.Text('System Monitoring Active', font=('Helvetica', 12))],
        [sg.Text('Security Logging Active', font=('Helvetica', 12))],
        [sg.Text('Cloud Sync: Disabled (not configured)', font=('Helvetica', 12))],
        [sg.HorizontalSeparator()],
        [sg.Button('View Processes'), sg.Button('View Security Events'), sg.Button('Exit')],
        [sg.Multiline('', size=(80, 20), key='-OUTPUT-', disabled=True)]
    ]
    
    window = sg.Window('VIGIL Dashboard', layout, size=(800, 600))
    
    while True:
        event, values = window.read()
        if event in (sg.WINDOW_CLOSED, 'Exit'):
            break
        elif event == 'View Processes':
            window['-OUTPUT-'].update('Process monitoring is active...\n')
        elif event == 'View Security Events':
            window['-OUTPUT-'].update('Security logging is active...\n')
    
    window.close()

if __name__ == '__main__':
    create_simple_dashboard()