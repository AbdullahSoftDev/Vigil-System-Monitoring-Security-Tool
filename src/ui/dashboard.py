"""
VIGIL Dashboard - Tkinter-based monitoring interface.
Updated with color-changing graphs and critical alerts.
"""
import sys
import os
import threading
import queue
import time
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path
import logging
import tkinter as tk


# Third-party imports
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
import matplotlib

# Use TkAgg backend
matplotlib.use('TkAgg')

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext, simpledialog
from tkinter import font as tkfont

# Local imports
from ..core.system_monitor import SystemMonitor
from ..core.security_logger import SecurityLogger
from ..core.alert_manager import AlertManager, AlertSeverity, AlertCategory
from ..core.config_manager import ConfigManager
from ..core.cloud_sync import CloudSync

# Setup logging
logger = logging.getLogger(__name__)

class AutoScrollbar(ttk.Scrollbar):
    """A scrollbar that hides itself when not needed."""
    def set(self, lo, hi):
        if float(lo) <= 0.0 and float(hi) >= 1.0:
            self.grid_remove()
        else:
            self.grid()
        ttk.Scrollbar.set(self, lo, hi)
    
    def pack(self, **kw):
        raise tk.TclError("Cannot use pack with this widget")
    
    def place(self, **kw):
        raise tk.TclError("Cannot use place with this widget")

class LiveGraph:
    """Manages live updating graphs for metrics with color-changing lines."""
    
    def __init__(self, parent, figsize=(10, 3), ylim=(0, 100), title="", ylabel="", dynamic_ylim=False, graph_type="cpu"):
        self.dynamic_ylim = dynamic_ylim
        self.ylim = ylim
        self.graph_type = graph_type  # 'cpu', 'memory', 'network'
        self.figure, self.ax = plt.subplots(figsize=figsize)
        self.ax.set_title(title, fontsize=12)
        self.ax.set_ylabel(ylabel, fontsize=10)
        self.ax.set_ylim(ylim)
        self.ax.set_xlabel("Time (seconds)", fontsize=10)
        self.ax.grid(True, alpha=0.3)
        self.ax.tick_params(labelsize=9)
        self.ax.set_facecolor('#f0f0f0')
        
        # Make the figure layout tight
        self.figure.tight_layout()
        self.figure.patch.set_facecolor('#f0f0f0')
        
        # Create canvas
        self.canvas = FigureCanvasTkAgg(self.figure, parent)
        self.canvas.draw()
        self.canvas_widget = self.canvas.get_tk_widget()
        
        # Initialize data
        self.x_data = []
        self.y_data = []
        self.line, = self.ax.plot([], [], linewidth=2.5, alpha=0.9)
        self.max_points = 60  # Show last 60 seconds
        
    def get_widget(self):
        """Return the canvas widget."""
        return self.canvas_widget
    
    def get_color_for_value(self, value):
        """Return color based on value thresholds."""
        if self.graph_type == "cpu":
            if value >= 90:
                return '#ff0000'  # Red for CRITICAL
            elif value >= 75:
                return '#ff6600'  # Orange for HIGH
            elif value >= 50:
                return '#ffcc00'  # Yellow for MEDIUM
            else:
                return '#00cc00'  # Green for normal
        elif self.graph_type == "memory":
            if value >= 90:
                return '#ff0000'  # Red for CRITICAL
            elif value >= 80:
                return '#ff6600'  # Orange for HIGH
            elif value >= 60:
                return '#ffcc00'  # Yellow for MEDIUM
            else:
                return '#00cc00'  # Green for normal
        else:  # network
            if value >= 1000:  # 1 MB/s
                return '#ff0000'  # Red for high traffic
            elif value >= 500:
                return '#ff6600'  # Orange for medium-high
            elif value >= 100:
                return '#ffcc00'  # Yellow for medium
            else:
                return '#0066cc'  # Blue for normal network
    
    def update(self, new_value: float, timestamp: Optional[datetime] = None):
        """Update the graph with new value and color."""
        if timestamp is None:
            timestamp = datetime.now()
        
        if not self.x_data:
            self.start_time = timestamp
            time_offset = 0
        else:
            time_offset = (timestamp - self.start_time).total_seconds()
        
        self.x_data.append(time_offset)
        self.y_data.append(new_value)
        
        # Keep only last max_points
        if len(self.x_data) > self.max_points:
            self.x_data = self.x_data[-self.max_points:]
            self.y_data = self.y_data[-self.max_points:]
        
        # Update line color based on latest value
        if self.y_data:
            latest_color = self.get_color_for_value(self.y_data[-1])
            self.line.set_color(latest_color)
        
        self.line.set_data(self.x_data, self.y_data)
        
        # Adjust y-axis dynamically for network graph
        if self.dynamic_ylim and self.y_data:
            max_val = max(self.y_data) if self.y_data else 10
            # Add 20% padding
            self.ax.set_ylim(0, max_val * 1.2 if max_val > 0 else 10)
        else:
            self.ax.set_ylim(self.ylim)
        
        # Adjust x-axis
        if len(self.x_data) > 1:
            self.ax.set_xlim(max(0, self.x_data[0]), self.x_data[-1] + 1)
        
        self.ax.relim()
        self.ax.autoscale_view(scalex=True, scaley=False)
        self.figure.tight_layout()
        self.canvas.draw()
    
    def clear(self):
        """Clear the graph data."""
        self.x_data = []
        self.y_data = []
        self.line.set_data([], [])
        self.ax.set_ylim(self.ylim)
        self.line.set_color('#0066cc')  # Reset to blue
        self.canvas.draw()

class AlertPanel:
    """Manages the alerts display panel."""
    
    def __init__(self, parent, alert_manager):
        self.parent = parent
        self.alert_manager = alert_manager
        self.selected_alerts = set()
        
        # Define alert colors based on severity
        self.severity_colors = {
            AlertSeverity.INFO: ('#007ACC', 'white'),
            AlertSeverity.LOW: ('#00CC00', 'white'),
            AlertSeverity.MEDIUM: ('#FFCC00', 'black'),
            AlertSeverity.HIGH: ('#FF6600', 'white'),
            AlertSeverity.CRITICAL: ('#CC0000', 'white')
        }
        
        # Define alert icons
        self.category_icons = {
            AlertCategory.PERFORMANCE: '📊',
            AlertCategory.SECURITY: '🛡️',
            AlertCategory.SYSTEM: '⚙️',
            AlertCategory.CORRELATION: '🔗'
        }
        
        self.create_widgets()
    
    def create_widgets(self):
        """Create alert panel widgets."""
        # Create main frame
        self.frame = ttk.Frame(self.parent)
        
        # Header frame
        header_frame = ttk.Frame(self.frame)
        header_frame.grid(row=0, column=0, columnspan=2, sticky='ew', padx=5, pady=5)
        
        # Alerts label
        self.alert_label = ttk.Label(header_frame, text="Active Alerts:", font=('Helvetica', 12, 'bold'))
        self.alert_label.pack(side=tk.LEFT)
        
        # Test button
        ttk.Button(header_frame, text="Test Alert", 
                  command=self.create_test_alert).pack(side=tk.RIGHT, padx=5)
        
        # Create treeview for alerts
        columns = ('Ack', 'Icon', 'Time', 'Severity', 'Source', 'Description')
        self.tree = ttk.Treeview(self.frame, columns=columns, show='headings', height=15)
        
        # Define headings
        self.tree.heading('Ack', text='Ack')
        self.tree.heading('Icon', text='Icon')
        self.tree.heading('Time', text='Time')
        self.tree.heading('Severity', text='Severity')
        self.tree.heading('Source', text='Source')
        self.tree.heading('Description', text='Description')
        
        # Define column widths
        self.tree.column('Ack', width=40, minwidth=40)
        self.tree.column('Icon', width=40, minwidth=40)
        self.tree.column('Time', width=80, minwidth=70)
        self.tree.column('Severity', width=80, minwidth=70)
        self.tree.column('Source', width=100, minwidth=80)
        self.tree.column('Description', width=400, minwidth=200)
        
        # Add scrollbar
        scrollbar = AutoScrollbar(self.frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        
        # Grid widgets
        self.tree.grid(row=1, column=0, sticky='nsew', padx=5, pady=5)
        scrollbar.grid(row=1, column=1, sticky='ns', pady=5)
        
        # Configure grid weights
        self.frame.grid_rowconfigure(1, weight=1)
        self.frame.grid_columnconfigure(0, weight=1)
        
        # Bind double-click event
        self.tree.bind('<Double-Button-1>', self.on_alert_double_click)
    
    def get_frame(self):
        """Return the frame widget."""
        return self.frame
    
    def create_alert_row(self, alert):
        """Create a single alert row for the tree."""
        icon = self.category_icons.get(getattr(alert, 'category', AlertCategory.SYSTEM), '📌')
        
        # Format timestamp
        if hasattr(alert, 'timestamp') and alert.timestamp:
            timestamp = alert.timestamp.strftime('%H:%M:%S')
        else:
            timestamp = 'N/A'
        
        # Use description or message
        if hasattr(alert, 'description') and alert.description:
            description = alert.description
        else:
            description = getattr(alert, 'message', 'No description')
        
        # Truncate description if too long
        if len(description) > 80:
            description = description[:77] + '...'
        
        # Check if acknowledged
        if hasattr(alert, 'status'):
            ack_icon = '✓' if alert.status.value == 'acknowledged' else '✗'
        else:
            ack_icon = '✗'
        
        # Get severity value
        if hasattr(alert, 'severity'):
            if hasattr(alert.severity, 'value'):
                severity = alert.severity.value.upper()
            else:
                severity = str(alert.severity).upper()
        else:
            severity = 'UNKNOWN'
        
        # Get source
        source = getattr(alert, 'source', 'System')
        
        return [ack_icon, icon, timestamp, severity, source, description], getattr(alert, 'id', 'unknown')
    
    def update_alerts_table(self, alerts=None):
        """Update the alerts table in the UI."""
        if alerts is None:
            alerts = self.alert_manager.get_recent_alerts(limit=50)
        
        # Clear existing items
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        # Add new items
        critical_count = 0
        high_count = 0
        
        for alert in alerts:
            try:
                row_data, alert_id = self.create_alert_row(alert)
                item = self.tree.insert('', tk.END, values=row_data)
                # Store ID as tags
                self.tree.item(item, tags=(alert_id,))
                
                # Apply colors based on severity and count critical/high
                if hasattr(alert, 'severity'):
                    severity = alert.severity
                    if severity == AlertSeverity.CRITICAL:
                        self.tree.tag_configure('critical', background='#FFCCCC')
                        self.tree.item(item, tags=(alert_id, 'critical'))
                        critical_count += 1
                    elif severity == AlertSeverity.HIGH:
                        self.tree.tag_configure('high', background='#FFE6CC')
                        self.tree.item(item, tags=(alert_id, 'high'))
                        high_count += 1
                    elif severity == AlertSeverity.MEDIUM:
                        self.tree.tag_configure('medium', background='#FFFFCC')
                        self.tree.item(item, tags=(alert_id, 'medium'))
            except Exception as e:
                logger.error(f"Error adding alert row: {e}")
                continue
        
        # Update alert count with visual indicators
        unack_count = sum(1 for a in alerts if hasattr(a, 'status') and a.status.value != 'acknowledged')
        
        # Update label with counts
        if critical_count > 0:
            self.alert_label.config(text=f"Active Alerts: {unack_count} (🔥 {critical_count} CRITICAL)")
        elif high_count > 0:
            self.alert_label.config(text=f"Active Alerts: {unack_count} (⚠️ {high_count} HIGH)")
        else:
            self.alert_label.config(text=f"Active Alerts: {unack_count}")
        
        return unack_count
    
    def create_test_alert(self):
        """Create a test alert."""
        if hasattr(self.alert_manager, 'create_test_alert'):
            try:
                alert_id = self.alert_manager.create_test_alert()
                self.update_alerts_table()
                messagebox.showinfo("Test Alert", f"Test alert created with ID: {alert_id}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to create test alert: {e}")
        else:
            messagebox.showwarning("Not Available", "Test alert feature not available")
    
    def on_alert_double_click(self, event):
        """Handle double-click on alerts table."""
        item = self.tree.selection()
        if item:
            tags = self.tree.item(item[0], 'tags')
            alert_id = tags[0] if tags else None
            if alert_id:
                self.show_alert_details(alert_id)
    
    def show_alert_details(self, alert_id):
        """Show detailed view of an alert."""
        alert = self.alert_manager.get_alert(alert_id)
        if not alert:
            return
        
        # Create detail window
        detail_window = tk.Toplevel(self.parent)
        detail_window.title("Alert Details")
        detail_window.geometry("600x500")
        detail_window.transient(self.parent)
        detail_window.grab_set()
        
        # Create main frame
        frame = ttk.Frame(detail_window, padding="10")
        frame.grid(row=0, column=0, sticky='nsew')
        
        # Title with severity color
        severity = getattr(alert, 'severity', AlertSeverity.MEDIUM)
        severity_color = self.severity_colors.get(severity, ('white', 'black'))[0]
        
        title_label = tk.Label(frame, text=getattr(alert, 'type', 'Alert'), 
                              font=('Helvetica', 14, 'bold'),
                              bg=severity_color, fg='white', padx=10, pady=5)
        title_label.grid(row=0, column=0, columnspan=2, sticky='ew', pady=(0, 10))
        
        # Separator
        ttk.Separator(frame, orient='horizontal').grid(row=1, column=0, columnspan=2, sticky='ew', pady=5)
        
        # Details grid
        row = 2
        
        # Source
        ttk.Label(frame, text="Source:", font=('Helvetica', 10, 'bold')).grid(row=row, column=0, sticky='w', pady=2)
        ttk.Label(frame, text=getattr(alert, 'source', 'Unknown')).grid(row=row, column=1, sticky='w', pady=2)
        row += 1
        
        # Category
        ttk.Label(frame, text="Category:", font=('Helvetica', 10, 'bold')).grid(row=row, column=0, sticky='w', pady=2)
        category = getattr(alert, 'category', AlertCategory.SYSTEM)
        category_text = category.value if hasattr(category, 'value') else str(category)
        ttk.Label(frame, text=category_text).grid(row=row, column=1, sticky='w', pady=2)
        row += 1
        
        # Severity
        ttk.Label(frame, text="Severity:", font=('Helvetica', 10, 'bold')).grid(row=row, column=0, sticky='w', pady=2)
        severity_text = severity.value.upper() if hasattr(severity, 'value') else str(severity)
        severity_label = tk.Label(frame, text=severity_text, bg=severity_color, fg='white', padx=5, pady=2)
        severity_label.grid(row=row, column=1, sticky='w', pady=2)
        row += 1
        
        # Time
        ttk.Label(frame, text="Time:", font=('Helvetica', 10, 'bold')).grid(row=row, column=0, sticky='w', pady=2)
        timestamp = getattr(alert, 'timestamp', datetime.now())
        ttk.Label(frame, text=str(timestamp)).grid(row=row, column=1, sticky='w', pady=2)
        row += 1
        
        # Separator
        ttk.Separator(frame, orient='horizontal').grid(row=row, column=0, columnspan=2, sticky='ew', pady=10)
        row += 1
        
        # Description
        ttk.Label(frame, text="Description:", font=('Helvetica', 10, 'bold')).grid(row=row, column=0, sticky='nw', pady=2)
        desc_text = scrolledtext.ScrolledText(frame, width=60, height=5, wrap=tk.WORD)
        desc_text.grid(row=row, column=1, sticky='w', pady=2)
        description = getattr(alert, 'description', getattr(alert, 'message', ''))
        desc_text.insert('1.0', description)
        desc_text.configure(state='disabled')
        row += 1
        
        # Data if available
        if hasattr(alert, 'data') and alert.data:
            ttk.Label(frame, text="Data:", font=('Helvetica', 10, 'bold')).grid(row=row, column=0, sticky='nw', pady=(10, 2))
            data_text = scrolledtext.ScrolledText(frame, width=60, height=8, wrap=tk.WORD)
            data_text.grid(row=row, column=1, sticky='w', pady=(10, 2))
            data_text.insert('1.0', json.dumps(alert.data, indent=2, default=str))
            data_text.configure(state='disabled')
            row += 1
        
        # Separator
        ttk.Separator(frame, orient='horizontal').grid(row=row, column=0, columnspan=2, sticky='ew', pady=10)
        row += 1
        
        # Buttons frame
        button_frame = ttk.Frame(frame)
        button_frame.grid(row=row, column=0, columnspan=2, pady=10)
        
        ttk.Button(button_frame, text="Acknowledge", 
                  command=lambda: self.acknowledge_alert(alert_id, detail_window)).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Close", 
                  command=detail_window.destroy).pack(side=tk.LEFT, padx=5)
        
        # Configure grid weights
        frame.grid_rowconfigure(row, weight=1)
        frame.grid_columnconfigure(1, weight=1)
        
        # Center window
        detail_window.update_idletasks()
        width = detail_window.winfo_width()
        height = detail_window.winfo_height()
        x = (detail_window.winfo_screenwidth() // 2) - (width // 2)
        y = (detail_window.winfo_screenheight() // 2) - (height // 2)
        detail_window.geometry(f'{width}x{height}+{x}+{y}')
    
    def acknowledge_alert(self, alert_id, window):
        """Acknowledge an alert."""
        self.alert_manager.acknowledge_alert(alert_id)
        messagebox.showinfo("Success", "Alert acknowledged!")
        window.destroy()
        self.update_alerts_table()

class ProcessPanel:
    """Manages the processes display panel."""
    def __init__(self, parent, system_monitor):
        self.parent = parent
        self.system_monitor = system_monitor
        self.sort_column = 2
        self.sort_ascending = False
        self.test_processes = []  # Store test processes
        self.create_widgets()
    
    def create_widgets(self):
        """Create process panel widgets."""
        self.frame = ttk.Frame(self.parent)
        
        header_frame = ttk.Frame(self.frame)
        header_frame.grid(row=0, column=0, columnspan=2, sticky='ew', pady=5)
        
        ttk.Label(header_frame, text="Process Manager", font=('Helvetica', 12, 'bold')).pack(side=tk.LEFT, padx=5)
        
        sort_frame = ttk.Frame(header_frame)
        sort_frame.pack(side=tk.RIGHT, padx=5)
        
        ttk.Button(sort_frame, text="PID", command=lambda: self.sort_by(0)).pack(side=tk.LEFT, padx=2)
        ttk.Button(sort_frame, text="Name", command=lambda: self.sort_by(1)).pack(side=tk.LEFT, padx=2)
        ttk.Button(sort_frame, text="CPU%", command=lambda: self.sort_by(2)).pack(side=tk.LEFT, padx=2)
        ttk.Button(sort_frame, text="Mem%", command=lambda: self.sort_by(3)).pack(side=tk.LEFT, padx=2)
        ttk.Button(sort_frame, text="User", command=lambda: self.sort_by(4)).pack(side=tk.LEFT, padx=2)
        ttk.Button(sort_frame, text="Refresh", command=self.update_processes_table).pack(side=tk.LEFT, padx=2)
        
        columns = ('PID', 'Name', 'CPU%', 'Mem%', 'User', 'Command')
        self.tree = ttk.Treeview(self.frame, columns=columns, show='headings', height=15)
        
        for col in columns:
            self.tree.heading(col, text=col)
        
        self.tree.column('PID', width=70, minwidth=50)
        self.tree.column('Name', width=150, minwidth=100)
        self.tree.column('CPU%', width=70, minwidth=50)
        self.tree.column('Mem%', width=70, minwidth=50)
        self.tree.column('User', width=100, minwidth=70)
        self.tree.column('Command', width=400, minwidth=200)
        
        vscroll = AutoScrollbar(self.frame, orient=tk.VERTICAL, command=self.tree.yview)
        hscroll = AutoScrollbar(self.frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=vscroll.set, xscrollcommand=hscroll.set)
        
        self.tree.grid(row=1, column=0, sticky='nsew', padx=5, pady=5)
        vscroll.grid(row=1, column=1, sticky='ns', pady=5)
        hscroll.grid(row=2, column=0, sticky='ew', padx=5)
        
        button_frame = ttk.Frame(self.frame)
        button_frame.grid(row=3, column=0, columnspan=2, pady=5)
        
        ttk.Button(button_frame, text="Kill Process", command=self.kill_process).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Add Test Process", command=self.add_test_process).pack(side=tk.LEFT, padx=5)
        
        self.total_label = ttk.Label(button_frame, text="Total Processes: 0")
        self.total_label.pack(side=tk.RIGHT, padx=5)
        
        self.frame.grid_rowconfigure(1, weight=1)
        self.frame.grid_columnconfigure(0, weight=1)
    
    def get_frame(self):
        """Return the frame widget."""
        return self.frame
    
    def sort_by(self, column):
        """Sort processes by column."""
        if self.sort_column == column:
            self.sort_ascending = not self.sort_ascending
        else:
            self.sort_column = column
            self.sort_ascending = False
        
        self.update_processes_table()
    
    def add_test_process(self):
        """Add a test process to the list."""
        import random
        import string
        
        # Generate a random test process
        test_pid = 90000 + len(self.test_processes)
        test_name = f"test_process_{''.join(random.choices(string.ascii_lowercase, k=4))}"
        
        test_process = {
            'pid': test_pid,
            'name': test_name,
            'cpu_percent': random.uniform(0.5, 5.0),
            'memory_percent': random.uniform(0.1, 2.0),
            'username': 'test_user',
            'cmdline': f'/usr/bin/python -m {test_name}',
            'is_test': True
        }
        
        self.test_processes.append(test_process)
        self.update_processes_table()
        messagebox.showinfo("Test Process", f"Added test process: {test_name} (PID: {test_pid})")
    
    def update_processes_table(self, processes=None):
        """Update the processes table in the UI."""
        real_processes = []
        
        if processes is None:
            try:
                if hasattr(self.system_monitor, 'get_processes'):
                    real_processes = self.system_monitor.get_processes(limit=50)
                else:
                    real_processes = self.system_monitor.get_running_processes()[:50]
            except Exception as e:
                logger.error(f"Error getting processes: {e}")
                real_processes = []
        
        # Combine real processes with test processes
        all_processes = list(real_processes) + self.test_processes
    
        for item in self.tree.get_children():
            self.tree.delete(item)
    
        table_data = []
        for proc in all_processes:
            # Check if it's a test process (has 'is_test' key)
            is_test = proc.get('is_test', False)
            
            # Format command with indicator for test processes
            cmd = (proc.get('cmdline', '') or '')[:100]
            if is_test:
                cmd = f"[TEST] {cmd}"
            
            table_data.append([
                proc.get('pid', 0),
                proc.get('name', 'N/A'),
                f"{proc.get('cpu_percent', 0):.1f}",
                f"{proc.get('memory_percent', 0):.1f}",
                proc.get('username', 'N/A'),
                cmd
            ])
    
        if self.sort_column is not None and table_data:
            try:
                reverse = not self.sort_ascending
                if self.sort_column == 2 or self.sort_column == 3:
                    table_data.sort(
                        key=lambda x: float(x[self.sort_column].rstrip('%')),
                        reverse=reverse
                    )
                else:
                    table_data.sort(
                        key=lambda x: x[self.sort_column],
                        reverse=reverse
                    )
            except:
                pass
    
        for row in table_data:
            item = self.tree.insert('', tk.END, values=row)
            try:
                cpu = float(row[2].rstrip('%'))
                if cpu > 80:
                    self.tree.tag_configure('high_cpu', background='#FFCCCC')
                    self.tree.item(item, tags=('high_cpu',))
                elif cpu > 50:
                    self.tree.tag_configure('medium_cpu', background='#FFFFCC')
                    self.tree.item(item, tags=('medium_cpu',))
            except:
                pass
    
        process_count = len(all_processes)
        self.total_label.config(text=f"Total Processes: {process_count} (Test: {len(self.test_processes)})")
        return process_count
    
    def kill_process(self):
        """Kill selected process."""
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select a process to kill.")
            return
        
        item = selection[0]
        values = self.tree.item(item, 'values')
        pid = int(values[0])
        name = values[1]
        
        # Check if it's a test process (PID >= 90000)
        if pid >= 90000:
            # Remove from test processes list
            for i, proc in enumerate(self.test_processes):
                if proc['pid'] == pid:
                    removed = self.test_processes.pop(i)
                    self.update_processes_table()
                    messagebox.showinfo("Success", f"Test process {name} (PID: {pid}) removed!")
                    return
            
            messagebox.showerror("Error", f"Test process {pid} not found in list.")
            return
        
        # Real process - try to kill it
        if messagebox.askyesno("Confirm Kill", f"Kill real process {pid} ({name})?\nThis will terminate the actual system process!"):
            try:
                import psutil
                proc = psutil.Process(pid)
                proc.terminate()
                messagebox.showinfo("Success", f"Process {pid} terminated.")
                self.update_processes_table()
            except psutil.NoSuchProcess:
                messagebox.showerror("Error", f"Process {pid} no longer exists.")
            except psutil.AccessDenied:
                messagebox.showerror("Error", f"Permission denied to kill process {pid}.\nTry running as root.")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to kill process: {e}")

class SecurityPanel:
    """Manages the security events display panel."""
    
    def __init__(self, parent, security_logger):
        self.parent = parent
        self.security_logger = security_logger
        self.create_widgets()
    
    def create_widgets(self):
        """Create security panel widgets."""
        self.frame = ttk.Frame(self.parent)
        
        left_frame = ttk.Frame(self.frame)
        left_frame.grid(row=0, column=0, sticky='nsew', padx=5, pady=5)
        
        ttk.Label(left_frame, text="Recent Security Events", font=('Helvetica', 12, 'bold')).grid(row=0, column=0, sticky='w', pady=5)
        
        columns = ('Time', 'Type', 'Severity', 'User', 'Source IP', 'Description')
        self.tree = ttk.Treeview(left_frame, columns=columns, show='headings', height=15)
        
        for col in columns:
            self.tree.heading(col, text=col)
        
        self.tree.column('Time', width=80, minwidth=70)
        self.tree.column('Type', width=100, minwidth=80)
        self.tree.column('Severity', width=80, minwidth=70)
        self.tree.column('User', width=80, minwidth=70)
        self.tree.column('Source IP', width=100, minwidth=80)
        self.tree.column('Description', width=350, minwidth=200)
        
        scrollbar = AutoScrollbar(left_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        
        self.tree.grid(row=1, column=0, sticky='nsew', pady=5)
        scrollbar.grid(row=1, column=1, sticky='ns')
        
        button_frame = ttk.Frame(left_frame)
        button_frame.grid(row=2, column=0, columnspan=2, pady=5)
        
        ttk.Button(button_frame, text="Export Logs", command=self.export_logs).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Clear Old", command=self.clear_old).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Refresh", command=self.update_security_table).pack(side=tk.LEFT, padx=5)
        
        right_frame = ttk.LabelFrame(self.frame, text="Security Statistics", padding=10)
        right_frame.grid(row=0, column=1, sticky='nsew', padx=5, pady=5)
        
        self.stats_text = scrolledtext.ScrolledText(right_frame, width=30, height=15, wrap=tk.WORD)
        self.stats_text.pack(fill=tk.BOTH, expand=True)
        self.stats_text.configure(state='disabled')
        
        self.frame.grid_rowconfigure(0, weight=1)
        self.frame.grid_columnconfigure(0, weight=3)
        self.frame.grid_columnconfigure(1, weight=1)
        left_frame.grid_rowconfigure(1, weight=1)
        left_frame.grid_columnconfigure(0, weight=1)
    
    def get_frame(self):
        """Return the frame widget."""
        return self.frame
    
    def update_security_table(self, events=None):
        """Update the security events table."""
        if events is None:
            events = self.security_logger.get_recent_events(limit=50)
        
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        critical_count = 0
        high_count = 0
        
        for event in events:
            timestamp = event.get('timestamp', '')
            if isinstance(timestamp, str):
                try:
                    dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    timestamp = dt.strftime('%H:%M:%S')
                except:
                    pass
            
            severity = event.get('severity', '').lower()
            
            values = [
                timestamp,
                event.get('event_type', ''),
                severity.upper(),
                event.get('user', 'N/A'),
                event.get('source_ip', 'N/A'),
                event.get('description', '')[:80]
            ]
            
            item = self.tree.insert('', tk.END, values=values)
            
            if 'critical' in severity:
                self.tree.tag_configure('critical', background='#FFCCCC')
                self.tree.item(item, tags=('critical',))
                critical_count += 1
            elif 'high' in severity:
                self.tree.tag_configure('high', background='#FFE6CC')
                self.tree.item(item, tags=('high',))
                high_count += 1
            elif 'medium' in severity:
                self.tree.tag_configure('medium', background='#FFFFCC')
                self.tree.item(item, tags=('medium',))
        
        stats = self.security_logger.get_stats()
        total = stats.get('total_events', 0)
        
        # Update stats text with warning if critical events
        stats_text = f"Total Events: {total}\n"
        if critical_count > 0:
            stats_text += f"⚠️ CRITICAL: {critical_count}\n"
        if high_count > 0:
            stats_text += f"⚠️ HIGH: {high_count}\n"
        stats_text += "\nBy Severity:\n"
        
        for severity, count in stats.get('events_by_severity', {}).items():
            stats_text += f"  {severity}: {count}\n"
        
        stats_text += "\nRecent Activity (24h):\n"
        for activity in stats.get('recent_activity', []):
            stats_text += f"  {activity['event_type']}: {activity['count']}\n"
        
        self.stats_text.configure(state='normal')
        self.stats_text.delete('1.0', tk.END)
        self.stats_text.insert('1.0', stats_text)
        self.stats_text.configure(state='disabled')
        
        return len(events)
    
    def export_logs(self):
        """Export security logs."""
        try:
            # Get events first to check if there's data
            all_events = self.security_logger.get_recent_events(limit=10000)
            
            if not all_events:
                messagebox.showwarning("No Data", "No security events found to export.")
                return
            
            # Ask for time range
            time_window = tk.Toplevel(self.parent)
            time_window.title("Export Time Range")
            time_window.geometry("450x300")
            time_window.transient(self.parent)
            time_window.grab_set()
            
            frame = ttk.Frame(time_window, padding=20)
            frame.pack(fill=tk.BOTH, expand=True)
            
            ttk.Label(frame, text=f"Total events available: {len(all_events)}", 
                     font=('Helvetica', 10, 'bold')).grid(row=0, column=0, columnspan=2, pady=10)
            
            ttk.Label(frame, text="Start Time (YYYY-MM-DD):").grid(row=1, column=0, sticky='w', pady=5)
            start_entry = ttk.Entry(frame, width=20)
            start_entry.grid(row=1, column=1, sticky='ew', pady=5, padx=5)
            start_entry.insert(0, (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d'))
            
            ttk.Label(frame, text="End Time (YYYY-MM-DD):").grid(row=2, column=0, sticky='w', pady=5)
            end_entry = ttk.Entry(frame, width=20)
            end_entry.grid(row=2, column=1, sticky='ew', pady=5, padx=5)
            end_entry.insert(0, datetime.now().strftime('%Y-%m-%d'))
            
            ttk.Label(frame, text="Format:").grid(row=3, column=0, sticky='w', pady=5)
            format_var = tk.StringVar(value='json')
            format_combo = ttk.Combobox(frame, textvariable=format_var, values=['json', 'csv'], width=17)
            format_combo.grid(row=3, column=1, sticky='w', pady=5, padx=5)
            
            ttk.Label(frame, text="Include all fields?", font=('Helvetica', 9)).grid(row=4, column=0, sticky='w', pady=5)
            include_all_var = tk.BooleanVar(value=True)
            ttk.Checkbutton(frame, variable=include_all_var).grid(row=4, column=1, sticky='w', pady=5, padx=5)
            
            def do_export():
                try:
                    start_str = start_entry.get()
                    end_str = end_entry.get()
                    
                    start_time = datetime.strptime(start_str, '%Y-%m-%d') if start_str else None
                    end_time = datetime.strptime(end_str, '%Y-%m-%d') if end_str else None
                    
                    # Filter events by date
                    filtered_events = []
                    for event in all_events:
                        event_time = None
                        if 'timestamp' in event:
                            if isinstance(event['timestamp'], str):
                                try:
                                    event_time = datetime.fromisoformat(event['timestamp'].replace('Z', '+00:00'))
                                except:
                                    event_time = None
                            elif isinstance(event['timestamp'], datetime):
                                event_time = event['timestamp']
                        
                        if event_time:
                            if start_time and event_time < start_time:
                                continue
                            if end_time and event_time > end_time + timedelta(days=1):
                                continue
                        
                        filtered_events.append(event)
                    
                    if not filtered_events:
                        messagebox.showwarning("No Data", f"No events found in the selected date range.\nTotal events in database: {len(all_events)}")
                        return
                    
                    filename = filedialog.asksaveasfilename(
                        defaultextension=f".{format_var.get()}",
                        filetypes=[(f"{format_var.get().upper()} files", f"*.{format_var.get()}")]
                    )
                    
                    if filename:
                        import json
                        import csv
                        
                        # Prepare data for export
                        export_data = []
                        for event in filtered_events:
                            if include_all_var.get():
                                # Include all fields
                                export_data.append(event)
                            else:
                                # Include only essential fields
                                export_data.append({
                                    'timestamp': event.get('timestamp', ''),
                                    'event_type': event.get('event_type', ''),
                                    'severity': event.get('severity', ''),
                                    'user': event.get('user', ''),
                                    'source_ip': event.get('source_ip', ''),
                                    'description': event.get('description', '')[:100]
                                })
                        
                        if format_var.get() == 'json':
                            with open(filename, 'w') as f:
                                json.dump(export_data, f, indent=2, default=str)
                        else:  # csv
                            if export_data:
                                with open(filename, 'w', newline='') as f:
                                    fieldnames = export_data[0].keys()
                                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                                    writer.writeheader()
                                    writer.writerows(export_data)
                        
                        messagebox.showinfo("Export Complete", 
                                           f"Exported {len(export_data)} events to:\n{filename}\n\n"
                                           f"Date range: {start_str} to {end_str}")
                        time_window.destroy()
                
                except Exception as e:
                    messagebox.showerror("Export Error", f"Failed to export: {e}")
                    import traceback
                    traceback.print_exc()
            
            button_frame = ttk.Frame(frame)
            button_frame.grid(row=5, column=0, columnspan=2, pady=20)
            
            ttk.Button(button_frame, text="Export", command=do_export).pack(side=tk.LEFT, padx=5)
            ttk.Button(button_frame, text="Cancel", command=time_window.destroy).pack(side=tk.LEFT, padx=5)
            
            frame.grid_columnconfigure(1, weight=1)
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to export logs: {e}")
            import traceback
            traceback.print_exc()
    
    def clear_old(self):
        """Clear old security events."""
        try:
            days = tk.simpledialog.askinteger(
                "Clear Old Events",
                "Clear events older than (days):",
                parent=self.parent,
                initialvalue=30,
                minvalue=1,
                maxvalue=365
            )
            
            if days:
                if hasattr(self.security_logger, 'cleanup_old_events'):
                    deleted = self.security_logger.cleanup_old_events(days)
                    messagebox.showinfo("Cleanup Complete", f"Cleared {deleted} old events")
                else:
                    messagebox.showinfo("Info", f"Would remove events older than {days} days")
                self.update_security_table()
        
        except Exception as e:
            messagebox.showerror("Error", f"Failed to clear old events: {e}")

class CloudPanel:
    """Manages the cloud sync display panel."""
    
    def __init__(self, parent, cloud_sync):
        self.parent = parent
        self.cloud_sync = cloud_sync
        self.create_widgets()
    
    def create_widgets(self):
        """Create cloud panel widgets."""
        self.frame = ttk.Frame(self.parent)
        
        left_frame = ttk.LabelFrame(self.frame, text="Connection Status", padding=10)
        left_frame.grid(row=0, column=0, sticky='nsew', padx=5, pady=5)
        
        self.status_label = ttk.Label(left_frame, text="Cloud Sync: Not Configured", font=('Helvetica', 10))
        self.status_label.grid(row=0, column=0, sticky='w', pady=5)
        
        self.queue_label = ttk.Label(left_frame, text="Queue: N/A")
        self.queue_label.grid(row=1, column=0, sticky='w', pady=5)
        
        self.last_sync_label = ttk.Label(left_frame, text="Last Sync: N/A")
        self.last_sync_label.grid(row=2, column=0, sticky='w', pady=5)
        
        self.privacy_label = ttk.Label(left_frame, text="Privacy: N/A")
        self.privacy_label.grid(row=3, column=0, sticky='w', pady=5)
        
        ttk.Separator(left_frame, orient='horizontal').grid(row=4, column=0, sticky='ew', pady=10)
        
        button_frame = ttk.Frame(left_frame)
        button_frame.grid(row=5, column=0, sticky='ew', pady=5)
        
        self.sync_button = ttk.Button(button_frame, text="Sync Now", command=self.sync_now)
        self.sync_button.pack(side=tk.LEFT, padx=2)
        
        ttk.Button(button_frame, text="Configure", command=self.configure).pack(side=tk.LEFT, padx=2)
        
        right_frame = ttk.LabelFrame(self.frame, text="Sync Statistics", padding=10)
        right_frame.grid(row=0, column=1, sticky='nsew', padx=5, pady=5)
        
        self.stats_text = scrolledtext.ScrolledText(right_frame, width=30, height=10, wrap=tk.WORD)
        self.stats_text.pack(fill=tk.BOTH, expand=True)
        self.stats_text.configure(state='disabled')
        
        self.frame.grid_rowconfigure(0, weight=1)
        self.frame.grid_columnconfigure(0, weight=1)
        self.frame.grid_columnconfigure(1, weight=1)
    
    def get_frame(self):
        """Return the frame widget."""
        return self.frame
    
    def update_cloud_status(self):
        """Update the cloud sync status display."""
        if not self.cloud_sync:
            self.status_label.config(text="Cloud Sync: Not Configured", foreground='orange')
            self.queue_label.config(text="Queue: N/A")
            self.last_sync_label.config(text="Last Sync: N/A")
            self.privacy_label.config(text="Privacy: N/A")
            self.sync_button.config(state='disabled')
            return
        
        status = self.cloud_sync.get_sync_status()
        
        if status.get('online', False):
            self.status_label.config(text="Cloud Sync: Online ✓", foreground='green')
            self.sync_button.config(state='normal')
        else:
            self.status_label.config(text="Cloud Sync: Offline ✗", foreground='red')
            self.sync_button.config(state='disabled')
        
        queue_size = status.get('queue_size', 0)
        self.queue_label.config(text=f"Queue: {queue_size}")
        
        last_sync = status.get('last_sync')
        if last_sync:
            self.last_sync_label.config(text=f"Last Sync: {last_sync}")
        else:
            self.last_sync_label.config(text="Last Sync: Never")
    
    def sync_now(self):
        """Trigger immediate cloud sync."""
        if not self.cloud_sync:
            messagebox.showerror("Error", "Cloud sync not configured!")
            return
        
        try:
            stats = self.cloud_sync.sync_now()
            
            stats_text = f"Sync Results:\n"
            stats_text += f"Sent: {stats.get('sent', 0)}\n"
            stats_text += f"Received: {stats.get('received', 0)}\n"
            stats_text += f"Failed: {stats.get('failed', 0)}\n"
            stats_text += f"Duration: {stats.get('duration', 0):.1f}s\n"
            
            self.stats_text.configure(state='normal')
            self.stats_text.delete('1.0', tk.END)
            self.stats_text.insert('1.0', stats_text)
            self.stats_text.configure(state='disabled')
            
            messagebox.showinfo("Sync Complete", f"Sync completed!")
            self.update_cloud_status()
        
        except Exception as e:
            messagebox.showerror("Sync Error", f"Failed to sync: {e}")
    
    def configure(self):
        """Open cloud configuration dialog."""
        config_window = tk.Toplevel(self.parent)
        config_window.title("Cloud Configuration")
        config_window.geometry("500x300")
        config_window.transient(self.parent)
        config_window.grab_set()
        
        frame = ttk.Frame(config_window, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(frame, text="Supabase URL:", font=('Helvetica', 10, 'bold')).grid(row=0, column=0, sticky='w', pady=5)
        url_entry = ttk.Entry(frame, width=40)
        url_entry.grid(row=0, column=1, sticky='ew', pady=5, padx=5)
        
        ttk.Label(frame, text="Service Key:", font=('Helvetica', 10, 'bold')).grid(row=1, column=0, sticky='w', pady=5)
        key_entry = ttk.Entry(frame, width=40, show='*')
        key_entry.grid(row=1, column=1, sticky='ew', pady=5, padx=5)
        
        enable_var = tk.BooleanVar(value=True)
        enable_check = ttk.Checkbutton(frame, text="Enable Cloud Sync", variable=enable_var)
        enable_check.grid(row=2, column=0, columnspan=2, sticky='w', pady=10)
        
        def save_config():
            messagebox.showinfo("Success", "Configuration saved!")
            config_window.destroy()
        
        button_frame = ttk.Frame(frame)
        button_frame.grid(row=3, column=0, columnspan=2, pady=20)
        
        ttk.Button(button_frame, text="Test Connection", command=lambda: None).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Save", command=save_config).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=config_window.destroy).pack(side=tk.LEFT, padx=5)
        
        frame.grid_columnconfigure(1, weight=1)
    
    def apply_privacy(self):
        """Apply privacy level to cloud sync."""
        if not self.cloud_sync:
            messagebox.showerror("Error", "Cloud sync not configured!")
            return
        
        try:
            self.cloud_sync.set_privacy_level(self.privacy_var.get())
            messagebox.showinfo("Success", f"Privacy level set to: {self.privacy_var.get()}")
            self.update_cloud_status()
        
        except Exception as e:
            messagebox.showerror("Error", f"Failed to apply privacy level: {e}")

class VigilDashboard:
    """
    Main VIGIL Dashboard class implementing Tkinter interface.
    """
    
    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager
        self.config = config_manager.config
        
        self.system_monitor = None
        self.security_logger = None
        self.alert_manager = None
        self.cloud_sync = None
        
        self.root = None
        self.running = False
        self.update_thread = None
        self.event_queue = queue.Queue()
        
        self.cpu_graph = None
        self.memory_graph = None
        self.network_graph = None
        self.alert_panel = None
        self.process_panel = None
        self.security_panel = None
        self.cloud_panel = None
        
        self.notebook = None
        self.tabs = {}
        
        self.refresh_interval = 1000
        
        logger.info("VIGIL Dashboard initialized")
    
    def set_components(self, system_monitor, security_logger, alert_manager, cloud_sync=None):
        """Set the monitoring components."""
        self.system_monitor = system_monitor
        self.security_logger = security_logger
        self.alert_manager = alert_manager
        self.cloud_sync = cloud_sync
        logger.info("Components set for dashboard")
    
    def create_widgets(self):
        """Create all dashboard widgets."""
        self.root = tk.Tk()
        self.root.title("VIGIL - Security Monitoring System")
        self.root.geometry("1400x900")
        
        # Set minimum window size
        self.root.minsize(1200, 700)
        
        try:
            icon_path = Path(__file__).parent.parent / 'assets' / 'vigil_icon.png'
            if icon_path.exists():
                icon = tk.PhotoImage(file=str(icon_path))
                self.root.iconphoto(True, icon)
        except:
            pass
        
        self.create_menu()
        self.create_status_bar()
        
        # Create main paned window for resizable layout
        main_paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Left panel for notebook (tabs)
        left_panel = ttk.Frame(main_paned)
        main_paned.add(left_panel, weight=3)
        
        # Right panel for quick stats (optional)
        right_panel = ttk.Frame(main_paned, width=250)
        main_paned.add(right_panel, weight=1)
        
        # Create notebook in left panel
        self.notebook = ttk.Notebook(left_panel)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        
        self.create_overview_tab()
        self.create_processes_tab()
        self.create_security_tab()
        self.create_alerts_tab()
        self.create_cloud_tab()
        self.create_settings_tab()
        
        # Quick stats in right panel
        self.create_quick_stats(right_panel)
        
        self.notebook.bind('<<NotebookTabChanged>>', self.on_tab_changed)
    
    def create_quick_stats(self, parent):
        """Create quick statistics panel."""
        frame = ttk.LabelFrame(parent, text="Quick Stats", padding=10)
        frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # System load
        ttk.Label(frame, text="System Load:", font=('Helvetica', 10, 'bold')).pack(anchor='w', pady=(5,0))
        self.quick_load = ttk.Label(frame, text="0.00, 0.00, 0.00")
        self.quick_load.pack(anchor='w', pady=(0,10))
        
        # Top process
        ttk.Label(frame, text="Top Process:", font=('Helvetica', 10, 'bold')).pack(anchor='w')
        self.quick_top_proc = ttk.Label(frame, text="None")
        self.quick_top_proc.pack(anchor='w', pady=(0,10))
        
        # Security status
        ttk.Label(frame, text="Security Status:", font=('Helvetica', 10, 'bold')).pack(anchor='w')
        self.quick_security = ttk.Label(frame, text="No threats")
        self.quick_security.pack(anchor='w')
    
    def update_quick_stats(self):
        """Update quick stats panel."""
        try:
            if self.system_monitor:
                metrics = self.system_monitor.get_current_metrics()
                load = metrics.get('load_avg', '0.00, 0.00, 0.00')
                self.quick_load.config(text=load)
                
                # Get top process
                processes = self.system_monitor.get_processes(limit=1)
                if processes:
                    top = processes[0]
                    self.quick_top_proc.config(text=f"{top.get('name', 'N/A')} ({top.get('cpu_percent', 0):.1f}%)")
            
            if self.alert_manager and self.alert_panel:
                alerts = self.alert_manager.get_recent_alerts(limit=1)
                if alerts and hasattr(alerts[0], 'severity'):
                    severity = alerts[0].severity
                    if severity == AlertSeverity.CRITICAL:
                        self.quick_security.config(text="⚠️ CRITICAL ALERT", foreground='red')
                    elif severity == AlertSeverity.HIGH:
                        self.quick_security.config(text="⚠️ High Alert", foreground='orange')
                    else:
                        self.quick_security.config(text="No threats", foreground='green')
        except:
            pass
    
    def create_menu(self):
        """Create the menu bar."""
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Pause Monitoring", command=self.toggle_pause)
        file_menu.add_command(label="Run Diagnostics", command=self.run_diagnostics)
        file_menu.add_command(label="Generate Report", command=self.generate_report)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        
        view_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="View", menu=view_menu)
        view_menu.add_command(label="Refresh", command=self.update_ui, accelerator="F5")
        view_menu.add_command(label="Clear Graphs", command=self.clear_graphs)
        
        tools_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Tools", menu=tools_menu)
        tools_menu.add_command(label="Quick Settings", command=self.show_quick_settings)
        
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="About", command=self.show_about)
        
        self.root.bind('<F5>', lambda e: self.update_ui())
    
    def create_status_bar(self):
        """Create the status bar."""
        self.status_bar = ttk.Frame(self.root, relief=tk.SUNKEN)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        
        self.status_label = ttk.Label(self.status_bar, text="Ready")
        self.status_label.pack(side=tk.LEFT, padx=5)
        
        self.last_update_label = ttk.Label(self.status_bar, text="Last Update: Never")
        self.last_update_label.pack(side=tk.RIGHT, padx=5)
    
    def create_overview_tab(self):
        """Create the Overview tab with improved graphs."""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Overview")
        self.tabs['overview'] = tab
        
        # Create a canvas with scrollbar for the entire tab
        canvas = tk.Canvas(tab, highlightthickness=0)
        scrollbar = ttk.Scrollbar(tab, orient=tk.VERTICAL, command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Bind mousewheel to scroll
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        
        # Main content in scrollable frame
        main_frame = ttk.Frame(scrollable_frame)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Top metrics section
        metrics_frame = ttk.LabelFrame(main_frame, text="System Metrics", padding=15)
        metrics_frame.pack(fill=tk.X, pady=(0, 20))
        
        # CPU
        cpu_row = ttk.Frame(metrics_frame)
        cpu_row.pack(fill=tk.X, pady=5)
        ttk.Label(cpu_row, text="CPU Usage:", font=('Helvetica', 11)).pack(side=tk.LEFT, padx=5)
        self.cpu_bar = ttk.Progressbar(cpu_row, length=300, mode='determinate')
        self.cpu_bar.pack(side=tk.LEFT, padx=10)
        self.cpu_text = ttk.Label(cpu_row, text="0%", font=('Helvetica', 11, 'bold'), width=8)
        self.cpu_text.pack(side=tk.LEFT)
        
        # Memory
        mem_row = ttk.Frame(metrics_frame)
        mem_row.pack(fill=tk.X, pady=5)
        ttk.Label(mem_row, text="Memory Usage:", font=('Helvetica', 11)).pack(side=tk.LEFT, padx=5)
        self.memory_bar = ttk.Progressbar(mem_row, length=300, mode='determinate')
        self.memory_bar.pack(side=tk.LEFT, padx=10)
        self.memory_text = ttk.Label(mem_row, text="0%", font=('Helvetica', 11, 'bold'), width=8)
        self.memory_text.pack(side=tk.LEFT)
        
        # Disk
        disk_row = ttk.Frame(metrics_frame)
        disk_row.pack(fill=tk.X, pady=5)
        ttk.Label(disk_row, text="Disk Usage:", font=('Helvetica', 11)).pack(side=tk.LEFT, padx=5)
        self.disk_bar = ttk.Progressbar(disk_row, length=300, mode='determinate')
        self.disk_bar.pack(side=tk.LEFT, padx=10)
        self.disk_text = ttk.Label(disk_row, text="0%", font=('Helvetica', 11, 'bold'), width=8)
        self.disk_text.pack(side=tk.LEFT)
        
        # Network
        net_row = ttk.Frame(metrics_frame)
        net_row.pack(fill=tk.X, pady=5)
        ttk.Label(net_row, text="Network:", font=('Helvetica', 11)).pack(side=tk.LEFT, padx=5)
        net_frame = ttk.Frame(net_row)
        net_frame.pack(side=tk.LEFT, padx=10)
        self.net_up_label = ttk.Label(net_frame, text="↑ 0 KB/s", font=('Helvetica', 10), foreground='green')
        self.net_up_label.pack(anchor='w')
        self.net_down_label = ttk.Label(net_frame, text="↓ 0 KB/s", font=('Helvetica', 10), foreground='blue')
        self.net_down_label.pack(anchor='w')
        
        # System Info
        info_frame = ttk.LabelFrame(main_frame, text="System Information", padding=15)
        info_frame.pack(fill=tk.X, pady=(0, 20))
        
        info_grid = ttk.Frame(info_frame)
        info_grid.pack(fill=tk.X)
        
        # Two column layout
        left_info = ttk.Frame(info_grid)
        left_info.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        right_info = ttk.Frame(info_grid)
        right_info.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        ttk.Label(left_info, text="Uptime:", font=('Helvetica', 10, 'bold')).grid(row=0, column=0, sticky='w', pady=2)
        self.uptime_label = ttk.Label(left_info, text="0:00:00")
        self.uptime_label.grid(row=0, column=1, sticky='w', pady=2, padx=10)
        
        ttk.Label(left_info, text="Processes:", font=('Helvetica', 10, 'bold')).grid(row=1, column=0, sticky='w', pady=2)
        self.process_count_label = ttk.Label(left_info, text="0")
        self.process_count_label.grid(row=1, column=1, sticky='w', pady=2, padx=10)
        
        ttk.Label(left_info, text="Load Average:", font=('Helvetica', 10, 'bold')).grid(row=2, column=0, sticky='w', pady=2)
        self.load_avg_label = ttk.Label(left_info, text="0.00, 0.00, 0.00")
        self.load_avg_label.grid(row=2, column=1, sticky='w', pady=2, padx=10)
        
        ttk.Label(right_info, text="Security Events:", font=('Helvetica', 10, 'bold')).grid(row=0, column=0, sticky='w', pady=2)
        self.security_count_label = ttk.Label(right_info, text="0")
        self.security_count_label.grid(row=0, column=1, sticky='w', pady=2, padx=10)
        
        ttk.Label(right_info, text="Active Alerts:", font=('Helvetica', 10, 'bold')).grid(row=1, column=0, sticky='w', pady=2)
        self.alert_count_label = ttk.Label(right_info, text="0")
        self.alert_count_label.grid(row=1, column=1, sticky='w', pady=2, padx=10)
        
        # Graphs section
        graphs_frame = ttk.LabelFrame(main_frame, text="Performance Graphs", padding=15)
        graphs_frame.pack(fill=tk.BOTH, expand=True)
        
        # Configure grid for graphs
        graphs_frame.columnconfigure(0, weight=1)
        
        # CPU Graph
        cpu_label_frame = ttk.Frame(graphs_frame)
        cpu_label_frame.grid(row=0, column=0, sticky='ew', pady=(10,0))
        ttk.Label(cpu_label_frame, text="CPU Usage (Last 60 seconds)", font=('Helvetica', 12, 'bold')).pack(anchor='w')
        ttk.Label(cpu_label_frame, text="Green: Normal | Yellow: Medium | Orange: High | Red: Critical", 
                 font=('Helvetica', 9)).pack(anchor='w')
        
        cpu_graph_frame = ttk.Frame(graphs_frame, height=250)
        cpu_graph_frame.grid(row=1, column=0, sticky='nsew', pady=5)
        cpu_graph_frame.grid_propagate(False)
        self.cpu_graph = LiveGraph(cpu_graph_frame, figsize=(12, 3), title="", ylabel="CPU %", graph_type="cpu")
        self.cpu_graph.get_widget().pack(fill=tk.BOTH, expand=True)
        
        # Memory Graph
        mem_label_frame = ttk.Frame(graphs_frame)
        mem_label_frame.grid(row=2, column=0, sticky='ew', pady=(20,0))
        ttk.Label(mem_label_frame, text="Memory Usage (Last 60 seconds)", font=('Helvetica', 12, 'bold')).pack(anchor='w')
        ttk.Label(mem_label_frame, text="Green: Normal | Yellow: Medium | Orange: High | Red: Critical", 
                 font=('Helvetica', 9)).pack(anchor='w')
        
        mem_graph_frame = ttk.Frame(graphs_frame, height=250)
        mem_graph_frame.grid(row=3, column=0, sticky='nsew', pady=5)
        mem_graph_frame.grid_propagate(False)
        self.memory_graph = LiveGraph(mem_graph_frame, figsize=(12, 3), title="", ylabel="Memory %", graph_type="memory")
        self.memory_graph.get_widget().pack(fill=tk.BOTH, expand=True)
        
        # Network Graph
        net_label_frame = ttk.Frame(graphs_frame)
        net_label_frame.grid(row=4, column=0, sticky='ew', pady=(20,0))
        ttk.Label(net_label_frame, text="Network Activity (Last 60 seconds)", font=('Helvetica', 12, 'bold')).pack(anchor='w')
        ttk.Label(net_label_frame, text="Upload speed - Blue: Normal | Yellow: Medium | Orange: High | Red: Critical", 
                 font=('Helvetica', 9)).pack(anchor='w')
        
        net_graph_frame = ttk.Frame(graphs_frame, height=250)
        net_graph_frame.grid(row=5, column=0, sticky='nsew', pady=5)
        net_graph_frame.grid_propagate(False)
        self.network_graph = LiveGraph(net_graph_frame, figsize=(12, 3), 
                                       title="", ylabel="KB/s", 
                                       ylim=(0, 100), dynamic_ylim=True, graph_type="network")
        self.network_graph.get_widget().pack(fill=tk.BOTH, expand=True)
    
    def create_processes_tab(self):
        """Create the Processes tab."""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Processes")
        self.tabs['processes'] = tab
        
        if self.system_monitor:
            self.process_panel = ProcessPanel(tab, self.system_monitor)
            self.process_panel.get_frame().pack(fill=tk.BOTH, expand=True)
    
    def create_security_tab(self):
        """Create the Security tab."""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Security")
        self.tabs['security'] = tab
        
        if self.security_logger:
            self.security_panel = SecurityPanel(tab, self.security_logger)
            self.security_panel.get_frame().pack(fill=tk.BOTH, expand=True)
    
    def create_alerts_tab(self):
        """Create the Alerts tab."""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Alerts")
        self.tabs['alerts'] = tab
        
        if self.alert_manager:
            self.alert_panel = AlertPanel(tab, self.alert_manager)
            self.alert_panel.get_frame().pack(fill=tk.BOTH, expand=True)
    
    def create_cloud_tab(self):
        """Create the Cloud tab."""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Cloud")
        self.tabs['cloud'] = tab
        
        if self.cloud_sync:
            self.cloud_panel = CloudPanel(tab, self.cloud_sync)
            self.cloud_panel.get_frame().pack(fill=tk.BOTH, expand=True)
        else:
            ttk.Label(tab, text="Cloud sync not configured", font=('Helvetica', 12)).pack(pady=50)
            ttk.Button(tab, text="Configure Cloud Sync", command=self.configure_cloud).pack(pady=10)
    
    def create_settings_tab(self):
        """Create the Settings tab."""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Settings")
        self.tabs['settings'] = tab
        
        ttk.Label(tab, text="Settings will be available in the next update", font=('Helvetica', 12)).pack(pady=50)
    
    def on_tab_changed(self, event):
        """Handle tab change events."""
        tab_name = self.notebook.tab(self.notebook.select(), "text").lower()
        
        if tab_name == "processes" and self.process_panel:
            self.process_panel.update_processes_table()
        elif tab_name == "security" and self.security_panel:
            self.security_panel.update_security_table()
        elif tab_name == "alerts" and self.alert_panel:
            self.alert_panel.update_alerts_table()
        elif tab_name == "cloud" and self.cloud_panel:
            self.cloud_panel.update_cloud_status()
    
    def update_ui(self):
        """Update all UI elements with current data."""
        try:
            if not self.system_monitor or not self.root:
                return
            
            metrics = self.system_monitor.get_current_metrics()
            
            # Update progress bars with color hints
            cpu_percent = metrics.get('cpu_percent', 0)
            self.cpu_bar['value'] = cpu_percent
            self.cpu_text.config(text=f'{cpu_percent:.1f}%')
            
            # Change CPU bar color based on value (using style)
            if cpu_percent >= 90:
                self.cpu_text.config(foreground='red')
            elif cpu_percent >= 75:
                self.cpu_text.config(foreground='orange')
            elif cpu_percent >= 50:
                self.cpu_text.config(foreground='gold')
            else:
                self.cpu_text.config(foreground='green')
            
            if self.cpu_graph:
                self.cpu_graph.update(cpu_percent)
            
            memory_percent = metrics.get('memory_percent', 0)
            self.memory_bar['value'] = memory_percent
            self.memory_text.config(text=f'{memory_percent:.1f}%')
            
            # Change Memory bar color based on value
            if memory_percent >= 90:
                self.memory_text.config(foreground='red')
            elif memory_percent >= 80:
                self.memory_text.config(foreground='orange')
            elif memory_percent >= 60:
                self.memory_text.config(foreground='gold')
            else:
                self.memory_text.config(foreground='green')
            
            if self.memory_graph:
                self.memory_graph.update(memory_percent)
            
            disk_percent = metrics.get('disk_percent', 0)
            self.disk_bar['value'] = disk_percent
            self.disk_text.config(text=f'{disk_percent:.1f}%')
            
            # Change Disk bar color based on value
            if disk_percent >= 95:
                self.disk_text.config(foreground='red')
            elif disk_percent >= 85:
                self.disk_text.config(foreground='orange')
            else:
                self.disk_text.config(foreground='green')
            
            # Get network values
            net_sent = metrics.get('network_sent_kbps', 0)
            net_recv = metrics.get('network_recv_kbps', 0)
            
            # Format with arrows and colors
            sent_color = 'red' if net_sent > 500 else 'orange' if net_sent > 100 else 'green'
            recv_color = 'red' if net_recv > 500 else 'orange' if net_recv > 100 else 'blue'
            
            self.net_up_label.config(text=f'↑ {net_sent:.1f} KB/s', foreground=sent_color)
            self.net_down_label.config(text=f'↓ {net_recv:.1f} KB/s', foreground=recv_color)
            
            # Update network graph with actual values
            if self.network_graph:
                self.network_graph.update(net_sent)
            
            uptime = metrics.get('uptime', '0:00:00')
            self.uptime_label.config(text=uptime)
            self.process_count_label.config(text=str(metrics.get('process_count', 0)))
            self.load_avg_label.config(text=metrics.get('load_avg', '0.00, 0.00, 0.00'))
            
            if self.security_logger:
                stats = self.security_logger.get_stats()
                total_events = stats.get('total_events', 0)
                self.security_count_label.config(text=str(total_events))
            
            if self.alert_manager and self.alert_panel:
                unack_count = self.alert_panel.update_alerts_table()
                self.alert_count_label.config(text=str(unack_count))
                
                # Change alert count color based on severity
                if unack_count > 0:
                    # Check if any critical alerts
                    alerts = self.alert_manager.get_recent_alerts(limit=10)
                    has_critical = any(a.severity == AlertSeverity.CRITICAL for a in alerts if hasattr(a, 'severity'))
                    if has_critical:
                        self.alert_count_label.config(foreground='red', font=('Helvetica', 10, 'bold'))
                    else:
                        self.alert_count_label.config(foreground='orange', font=('Helvetica', 10, 'bold'))
                else:
                    self.alert_count_label.config(foreground='green')
            
            # Update quick stats
            self.update_quick_stats()
            
            self.last_update_label.config(text=f'Last Update: {datetime.now().strftime("%H:%M:%S")}')
            
        except Exception as e:
            logger.error(f"Error updating UI: {e}")
            self.status_label.config(text=f'Error: {str(e)[:50]}...')
    
    def clear_graphs(self):
        """Clear all graph data."""
        if self.cpu_graph:
            self.cpu_graph.clear()
        if self.memory_graph:
            self.memory_graph.clear()
        if self.network_graph:
            self.network_graph.clear()
    
    def toggle_pause(self):
        """Toggle monitoring pause state."""
        if self.system_monitor:
            if hasattr(self.system_monitor, 'running') and self.system_monitor.running:
                self.system_monitor.stop()
                self.status_label.config(text="Monitoring Paused")
            else:
                self.system_monitor.start()
                self.status_label.config(text="Monitoring Active")
    
    def run_diagnostics(self):
        """Run system diagnostics."""
        try:
            from ..utils.diagnostic import run_diagnostics
            results = run_diagnostics(self.system_monitor, self.security_logger, 
                                      self.alert_manager, self.cloud_sync, self.config_manager)
            
            result_window = tk.Toplevel(self.root)
            result_window.title("Diagnostic Results")
            result_window.geometry("800x600")
            
            text_area = scrolledtext.ScrolledText(result_window, wrap=tk.WORD, width=100, height=35)
            text_area.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
            
            result_text = "Diagnostic Results:\n\n"
            for category, tests in results.items():
                result_text += f"{category}:\n"
                for test_name, result in tests.items():
                    status = "✓" if result.get('status') == 'pass' else "✗"
                    result_text += f"  {status} {test_name}: {result.get('message', '')}\n"
                result_text += "\n"
            
            text_area.insert('1.0', result_text)
            text_area.configure(state='disabled')
            
        except Exception as e:
            messagebox.showerror("Diagnostics Error", f"Failed to run diagnostics: {e}")
    
    def generate_report(self):
        """Generate a system report."""
        try:
            import json
            
            report = {
                'timestamp': datetime.now().isoformat(),
                'system': {},
                'security': {},
                'alerts': {}
            }
            
            if self.system_monitor:
                metrics = self.system_monitor.get_current_metrics()
                report['system']['metrics'] = metrics
                report['system']['process_count'] = len(self.system_monitor.get_processes(limit=1000))
            
            if self.security_logger:
                stats = self.security_logger.get_stats()
                report['security'] = stats
            
            if self.alert_manager:
                alerts = self.alert_manager.get_recent_alerts(limit=100)
                report['alerts']['count'] = len(alerts)
                report['alerts']['unacknowledged'] = sum(1 for a in alerts if a.status.value != 'acknowledged')
            
            filename = filedialog.asksaveasfilename(
                defaultextension=".json",
                filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
            )
            
            if filename:
                with open(filename, 'w') as f:
                    json.dump(report, f, indent=2, default=str)
                
                messagebox.showinfo("Report Complete", f"Report saved to:\n{filename}")
        
        except Exception as e:
            messagebox.showerror("Report Error", f"Failed to generate report: {e}")
    
    def show_quick_settings(self):
        """Show quick settings dialog."""
        settings_window = tk.Toplevel(self.root)
        settings_window.title("Quick Settings")
        settings_window.geometry("400x300")
        settings_window.transient(self.root)
        settings_window.grab_set()
        
        frame = ttk.Frame(settings_window, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(frame, text="Quick Settings", font=('Helvetica', 14, 'bold')).pack(pady=10)
        ttk.Label(frame, text="Use the Settings tab for full configuration").pack(pady=5)
        
        ttk.Button(frame, text="Close", command=settings_window.destroy).pack(pady=20)
    
    def show_about(self):
        """Show about dialog."""
        about_window = tk.Toplevel(self.root)
        about_window.title("About VIGIL")
        about_window.geometry("500x400")
        about_window.transient(self.root)
        about_window.grab_set()
        
        frame = ttk.Frame(about_window, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(frame, text="VIGIL Security Monitoring System", 
                 font=('Helvetica', 16, 'bold')).pack(pady=10)
        
        ttk.Label(frame, text="Version: 2.0", font=('Helvetica', 11)).pack(pady=5)
        ttk.Label(frame, text="© 2024 VIGIL Project").pack(pady=5)
        
        ttk.Label(frame, text="\nA comprehensive security monitoring and alerting system for Linux.",
                 wraplength=400, justify=tk.CENTER).pack(pady=10)
        
        features = [
            "• Real-time CPU, Memory, Disk, Network monitoring",
            "• Security event detection and alerting",
            "• Process management with kill capability",
            "• File integrity monitoring",
            "• Authentication log parsing",
            "• Cloud sync with Supabase",
            "• AES-256 encryption for sensitive data"
        ]
        
        for feature in features:
            ttk.Label(frame, text=feature).pack(anchor='w', pady=2)
        
        ttk.Button(frame, text="Close", command=about_window.destroy).pack(pady=20)
    
    def configure_cloud(self):
        """Configure cloud sync."""
        messagebox.showinfo("Cloud Configuration", "Please configure cloud sync in the Settings tab or by editing config.yaml")
    
    def run(self):
        """Main dashboard run loop."""
        self.create_widgets()
        self.update_ui()
        self.running = True
        self.schedule_update()
        
        try:
            self.root.mainloop()
        finally:
            self.running = False
    
    def schedule_update(self):
        """Schedule the next UI update."""
        if self.running and self.root:
            self.update_ui()
            self.root.after(self.refresh_interval, self.schedule_update)

def main():
    """Main entry point for dashboard."""
    import sys
    import os
    
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    
    from src.core.config_manager import ConfigManager
    
    try:
        config = ConfigManager()
        dashboard = VigilDashboard(config)
        dashboard.run()
    except Exception as e:
        logger.error(f"Failed to start dashboard: {e}")
        messagebox.showerror("Fatal Error", f'Failed to start dashboard: {e}\n\nCheck logs for details.')

if __name__ == "__main__":
    main()