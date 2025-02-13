import ast
import csv
import io
import json
import logging
import os
import re
import subprocess
import sys
import tkinter as tk
import tkinter.filedialog as filedialog
import tkinter.messagebox as confirmDialog
import traceback
import webbrowser
from time import sleep
from tkinter import *

import requests
from config import appname
from monitor import monitor

from . import AutoCompleter, PlaceHolder
from .updater import SpanshUpdater

# We need a name of plugin dir, not SpanshRouter.py dir
plugin_name = os.path.basename(os.path.dirname(os.path.dirname(__file__)))
logger = logging.getLogger(f'{appname}.{plugin_name}')


class SpanshRouter():
    def __init__(self, plugin_dir):
        version_file = os.path.join(plugin_dir, "version.json")
        with open(version_file, 'r') as version_fd:
            self.plugin_version = version_fd.read()

        self.update_available = False
        self.roadtoriches = False
        self.fleetcarrier = False
        self.galaxy = False
        self.next_stop = "No route planned"
        self.route = []
        self.next_wp_label = "Next waypoint: "
        self.jumpcountlbl_txt = "Estimated jumps left: "
        self.bodieslbl_txt = "Bodies to scan at: "
        self.fleetstocklbl_txt = "Time to restock Tritium"
        self.refuellbl_txt = "Time to scoop some fuel"
        self.bodies = ""
        self.parent = None
        self.plugin_dir = plugin_dir
        self.save_route_path = os.path.join(plugin_dir, 'route.csv')
        self.export_route_path = os.path.join(plugin_dir, 'Export for TCE.exp')
        self.offset_file_path = os.path.join(plugin_dir, 'offset')
        self.offset = 0
        self.jumps_left = 0
        self.error_txt = tk.StringVar()
        self.plot_error = "Error while trying to plot a route, please try again."
        self.system_header = "System Name"
        self.bodyname_header = "Body Name"
        self.bodysubtype_header = "Body Subtype"
        self.jumps_header = "Jumps"
        self.restocktritium_header = "Restock Tritium"
        self.refuel_header = "Refuel"
        self.pleaserefuel = False

    #   -- GUI part --
    def init_gui(self, parent):
        self.parent = parent
        self.frame = tk.Frame(parent, borderwidth=2)
        self.frame.grid(sticky=tk.NSEW, columnspan=2)

        # Route info
        self.waypoint_prev_btn = tk.Button(self.frame, text="^", command=self.goto_prev_waypoint)
        self.waypoint_btn = tk.Button(self.frame, text=self.next_wp_label + '\n' + self.next_stop, command=self.copy_waypoint)
        self.waypoint_next_btn = tk.Button(self.frame, text="v", command=self.goto_next_waypoint)
        self.jumpcounttxt_lbl = tk.Label(self.frame, text=self.jumpcountlbl_txt + str(self.jumps_left))
        self.bodies_lbl = tk.Label(self.frame, justify=LEFT, text=self.bodieslbl_txt + self.bodies)
        self.fleetrestock_lbl = tk.Label(self.frame, justify=LEFT, text=self.fleetstocklbl_txt)
        self.refuel_lbl = tk.Label(self.frame, justify=LEFT, text=self.refuellbl_txt)
        self.error_lbl = tk.Label(self.frame, textvariable=self.error_txt)

        # Plotting GUI
        self.source_ac = AutoCompleter(self.frame, "Source System", width=30)
        self.dest_ac = AutoCompleter(self.frame, "Destination System", width=30)
        self.range_entry = PlaceHolder(self.frame, "Range (LY)", width=10)
        self.efficiency_slider = tk.Scale(self.frame, from_=1, to=100, orient=tk.HORIZONTAL, label="Efficiency (%)")
        self.efficiency_slider.set(60)
        self.plot_gui_btn = tk.Button(self.frame, text="Plot route", command=self.show_plot_gui)
        self.plot_route_btn = tk.Button(self.frame, text="Calculate", command=self.plot_route)
        self.cancel_plot = tk.Button(self.frame, text="Cancel", command=lambda: self.show_plot_gui(False))

        self.csv_route_btn = tk.Button(self.frame, text="Import file", command=self.plot_file)
        self.export_route_btn = tk.Button(self.frame, text="Export for TCE", command=self.export_route)
        self.clear_route_btn = tk.Button(self.frame, text="Clear route", command=self.clear_route)

        row = 0
        self.waypoint_prev_btn.grid(row=row, columnspan=2)
        row += 1
        self.waypoint_btn.grid(row=row, columnspan=2)
        row += 1
        self.waypoint_next_btn.grid(row=row, columnspan=2)
        row += 1
        self.bodies_lbl.grid(row=row, columnspan=2, sticky=tk.W)
        row += 1
        self.fleetrestock_lbl.grid(row=row, columnspan=2, sticky=tk.W)
        row += 1
        self.refuel_lbl.grid(row=row,columnspan=2, sticky=tk.W)
        row += 1
        self.source_ac.grid(row=row,columnspan=2, pady=(10,0)) # The AutoCompleter takes two rows to show the list when needed, so we skip one
        row += 2
        self.dest_ac.grid(row=row,columnspan=2, pady=(10,0))
        row += 2
        self.range_entry.grid(row=row, pady=10, sticky=tk.W)
        row += 1
        self.efficiency_slider.grid(row=row, pady=10, columnspan=2, sticky=tk.EW)
        row += 1
        self.csv_route_btn.grid(row=row, pady=10, padx=0)
        self.plot_route_btn.grid(row=row, pady=10, padx=0)
        self.plot_gui_btn.grid(row=row, column=1, pady=10, padx=5, sticky=tk.W)
        self.cancel_plot.grid(row=row, column=1, pady=10, padx=5, sticky=tk.E)
        row += 1
        self.export_route_btn.grid(row=row, pady=10, padx=0)
        self.clear_route_btn.grid(row=row, column=1, pady=10, padx=5, sticky=tk.W)
        row += 1
        self.jumpcounttxt_lbl.grid(row=row, pady=5, sticky=tk.W)
        row += 1
        self.error_lbl.grid(row=row, columnspan=2)
        self.error_lbl.grid_remove()
        row += 1

        # Check if we're having a valid range on the fly
        self.range_entry.var.trace('w', self.check_range)

        self.show_plot_gui(False)

        if not self.route.__len__() > 0:
            self.waypoint_prev_btn.grid_remove()
            self.waypoint_btn.grid_remove()
            self.waypoint_next_btn.grid_remove()
            self.jumpcounttxt_lbl.grid_remove()
            self.bodies_lbl.grid_remove()
            self.fleetrestock_lbl.grid_remove()
            self.export_route_btn.grid_remove()
            self.clear_route_btn.grid_remove()

        self.update_gui()

        return self.frame

    def show_plot_gui(self, show=True):
        if show:
            self.waypoint_prev_btn.grid_remove()
            self.waypoint_btn.grid_remove()
            self.waypoint_next_btn.grid_remove()
            self.jumpcounttxt_lbl.grid_remove()
            self.bodies_lbl.grid_remove()
            self.fleetrestock_lbl.grid_remove()
            self.export_route_btn.grid_remove()
            self.clear_route_btn.grid_remove()

            self.plot_gui_btn.grid_remove()
            self.csv_route_btn.grid_remove()
            self.source_ac.grid()
            # Prefill the "Source" entry with the current system
            self.source_ac.set_text(monitor.state['SystemName'] if monitor.state['SystemName'] is not None else "Source System", monitor.state['SystemName'] is None)
            self.dest_ac.grid()
            self.range_entry.grid()
            self.efficiency_slider.grid()
            self.plot_route_btn.grid()
            self.cancel_plot.grid()

            self.show_route_gui(False)

        else:
            if len(self.source_ac.var.get()) == 0:
                self.source_ac.put_placeholder()
            if len(self.dest_ac.var.get()) == 0:
                self.dest_ac.put_placeholder()
            self.source_ac.hide_list()
            self.source_ac.grid_remove()
            self.dest_ac.hide_list()
            self.dest_ac.grid_remove()
            self.range_entry.grid_remove()
            self.efficiency_slider.grid_remove()
            self.plot_gui_btn.grid_remove()
            self.plot_route_btn.grid_remove()
            self.cancel_plot.grid_remove()
            self.plot_gui_btn.grid()
            self.csv_route_btn.grid()
            self.show_route_gui(True)

    def set_source_ac(self, text):
        self.source_ac.delete(0, tk.END)
        self.source_ac.insert(0, text)
        self.source_ac.set_default_style()

    def show_route_gui(self, show):
        self.hide_error()
        if not show or not self.route.__len__() > 0:
            self.waypoint_prev_btn.grid_remove()
            self.waypoint_btn.grid_remove()
            self.waypoint_next_btn.grid_remove()
            self.jumpcounttxt_lbl.grid_remove()
            self.bodies_lbl.grid_remove()
            self.fleetrestock_lbl.grid_remove()
            self.refuel_lbl.grid_remove()
            self.export_route_btn.grid_remove()
            self.clear_route_btn.grid_remove()
        else:
            self.waypoint_btn["text"] = self.next_wp_label + '\n' + self.next_stop
            if self.jumps_left > 0:
                self.jumpcounttxt_lbl["text"] = self.jumpcountlbl_txt + str(self.jumps_left)
                self.jumpcounttxt_lbl.grid()
            else:
                self.jumpcounttxt_lbl.grid_remove()

            if self.roadtoriches:
                self.bodies_lbl["text"] = self.bodieslbl_txt + self.bodies
                self.bodies_lbl.grid()
            else:
                self.bodies_lbl.grid_remove()

            self.fleetrestock_lbl.grid_remove()
            if self.fleetcarrier:
                if self.offset > 0:
                    restock = self.route[self.offset - 1][2]
                    if restock.lower() == "yes":
                        self.fleetrestock_lbl["text"] = f"At: {self.route[self.offset - 1][0]}\n   {self.fleetstocklbl_txt}" 
                        self.fleetrestock_lbl.grid()

            if self.galaxy:
                if self.pleaserefuel:
                    self.refuel_lbl['text'] = self.refuellbl_txt
                    self.refuel_lbl.grid()
                else:
                    self.refuel_lbl.grid_remove()

            self.waypoint_prev_btn.grid()
            self.waypoint_btn.grid()
            self.waypoint_next_btn.grid()

            if self.offset == 0:
                self.waypoint_prev_btn.config(state=tk.DISABLED)
            else:
                self.waypoint_prev_btn.config(state=tk.NORMAL)

                if self.offset == self.route.__len__()-1:
                    self.waypoint_next_btn.config(state=tk.DISABLED)
                else:
                    self.waypoint_next_btn.config(state=tk.NORMAL)

            self.export_route_btn.grid()
            self.clear_route_btn.grid()

    def update_gui(self):
        self.show_route_gui(True)

    def show_error(self, error):
        self.error_txt.set(error)
        self.error_lbl.grid()

    def hide_error(self):
        self.error_lbl.grid_remove()

    def enable_plot_gui(self, enable):
        if enable:
            self.source_ac.config(state=tk.NORMAL)
            self.source_ac.update_idletasks()
            self.dest_ac.config(state=tk.NORMAL)
            self.dest_ac.update_idletasks()
            self.efficiency_slider.config(state=tk.NORMAL)
            self.efficiency_slider.update_idletasks()
            self.range_entry.config(state=tk.NORMAL)
            self.range_entry.update_idletasks()
            self.plot_route_btn.config(state=tk.NORMAL, text="Calculate")
            self.plot_route_btn.update_idletasks()
            self.cancel_plot.config(state=tk.NORMAL)
            self.cancel_plot.update_idletasks()
        else:
            self.source_ac.config(state=tk.DISABLED)
            self.source_ac.update_idletasks()
            self.dest_ac.config(state=tk.DISABLED)
            self.dest_ac.update_idletasks()
            self.efficiency_slider.config(state=tk.DISABLED)
            self.efficiency_slider.update_idletasks()
            self.range_entry.config(state=tk.DISABLED)
            self.range_entry.update_idletasks()
            self.plot_route_btn.config(state=tk.DISABLED, text="Computing...")
            self.plot_route_btn.update_idletasks()
            self.cancel_plot.config(state=tk.DISABLED)
            self.cancel_plot.update_idletasks()

    #   -- END GUI part --


    def open_last_route(self):
        try:
            has_headers = False
            with open(self.save_route_path, 'r', newline='') as csvfile:
                # Check if the file has a header for compatibility with previous versions
                dict_route_reader = csv.DictReader(csvfile)
                if dict_route_reader.fieldnames[0] == self.system_header:
                    has_headers = True

            if has_headers:
                self.plot_csv(self.save_route_path, clear_previous_route=False)
            else:
                with open(self.save_route_path, 'r', newline='') as csvfile:
                    route_reader = csv.reader(csvfile)

                    for row in route_reader:
                        if row not in (None, "", []):
                            self.route.append(row)

            try:
                with open(self.offset_file_path, 'r') as offset_fh:
                    self.offset = int(offset_fh.readline())

            except:
                self.offset = 0

            self.jumps_left = 0
            for row in self.route[self.offset:]:
                if row[1] not in [None, "", []]:
                    self.jumps_left += int(row[1])

            self.next_stop = self.route[self.offset][0]
            self.update_bodies_text()
            self.copy_waypoint()
            self.update_gui()

        except IOError:
            logger.info("No previously saved route")
        except:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
            logger.warning(''.join('!! ' + line for line in lines))

    def copy_waypoint(self):
        if sys.platform == "linux" or sys.platform == "linux2":
            command = subprocess.Popen(["echo", "-n", self.next_stop], stdout=subprocess.PIPE)
            subprocess.Popen(["xclip", "-selection", "c"], stdin=command.stdout)
        else:
            self.parent.clipboard_clear()
            self.parent.clipboard_append(self.next_stop)
            self.parent.update()

    def goto_next_waypoint(self):
        if self.offset < self.route.__len__()-1:
            self.update_route(1)

    def goto_prev_waypoint(self):
        if self.offset > 0:
            self.update_route(-1)

    def update_route(self, direction=1):
        if direction > 0:
            if self.route[self.offset][1] not in [None, "", []]:
                if not self.galaxy:
                    self.jumps_left -= int(self.route[self.offset][1])
                else:
                    self.jumps_left -= 1
            self.offset += 1
        else:
            self.offset -= 1
            if self.route[self.offset][1] not in [None, "", []]:
                if not self.galaxy:
                    self.jumps_left += int(self.route[self.offset][1])
                else:
                    self.jumps_left += 1

        if self.offset >= self.route.__len__():
            self.next_stop = "End of the road!"
            self.update_gui()
        else:
            self.next_stop = self.route[self.offset][0]
            self.update_bodies_text()

            if self.galaxy:
                self.pleaserefuel = self.route[self.offset][1] == "Yes"

            self.update_gui()
            self.copy_waypoint()
        self.save_offset()

    def goto_changelog_page(self):
        changelog_url = 'https://github.com/CMDR-Kiel42/EDMC_SpanshRouter/blob/master/CHANGELOG.md#'
        changelog_url += self.spansh_updater.version.replace('.', '')
        webbrowser.open(changelog_url)

    def plot_file(self):
        ftypes = [
            ('All supported files', '*.csv *.txt'),
            ('CSV files', '*.csv'),
            ('Text files', '*.txt'),
        ]
        filename = filedialog.askopenfilename(filetypes = ftypes, initialdir=os.path.expanduser('~'))

        if filename.__len__() > 0:
            try:
                ftype_supported = False
                if filename.endswith(".csv"):
                    ftype_supported = True
                    self.plot_csv(filename)

                elif filename.endswith(".txt"):
                    ftype_supported = True
                    self.plot_edts(filename)

                if ftype_supported:
                    self.offset = 0
                    self.next_stop = self.route[0][0]
                    if self.galaxy:
                        self.pleaserefuel = self.route[0][1] == "Yes"
                    self.update_bodies_text()
                    self.copy_waypoint()
                    self.update_gui()
                    self.save_all_route()
                else:
                    self.show_error("Unsupported file type")
            except:
                exc_type, exc_value, exc_traceback = sys.exc_info()
                lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
                logger.warning(''.join('!! ' + line for line in lines))
                self.enable_plot_gui(True)
                self.show_error("(1) An error occured while reading the file.")

    def plot_csv(self, filename, clear_previous_route=True):
       with io.open(filename, 'r', encoding='utf-8-sig', newline='') as csvfile:
            self.roadtoriches = False
            self.fleetcarrier = False
            self.galaxy = False
        
            if clear_previous_route:
                self.clear_route(False)
            
            route_reader = csv.DictReader(csvfile)
            
            # Get column header names as string
            headerline = ','.join(route_reader.fieldnames)

            # Define the differnt internal formats based on the CSV header row
            internalbasicheader1 = "System Name"
            internalbasicheader2 = "System Name,Jumps"
            internalrichesheader = "System Name,Jumps,Body Name,Body Subtype"
            internalfleetcarrierheader = "System Name,Jumps,Restock Tritium"
            internalgalaxyheader = "System Name,Refuel"
            # Define the differnt import file formats based on the CSV header row
            neutronimportheader = "System Name,Distance To Arrival,Distance Remaining,Neutron Star,Jumps"
            road2richesimportheader = "System Name,Body Name,Body Subtype,Is Terraformable,Distance To Arrival,Estimated Scan Value,Estimated Mapping Value,Jumps"
            fleetcarrierimportheader = "System Name,Distance,Distance Remaining,Fuel Used,Icy Ring,Pristine,Restock Tritium"
            galaxyimportheader = "System Name,Distance,Distance Remaining,Fuel Left,Fuel Used,Refuel,Neutron Star"

            if (headerline == internalbasicheader1) or (headerline == internalbasicheader2) or (headerline == neutronimportheader):
                for row in route_reader:
                    if row not in (None, "", []):
                        self.route.append([
                            row[self.system_header],
                            row.get(self.jumps_header, "") # Jumps column is optional
                        ])
                        if row.get(self.jumps_header): # Jumps column is optional
                            self.jumps_left += int(row[self.jumps_header])

            elif headerline == internalrichesheader:
                self.roadtoriches = True

                for row in route_reader:
                    if row not in (None, "", []):
                        # Convert string representations of lists to actual Lists
                        bodynames = ast.literal_eval(row[self.bodyname_header])
                        bodysubtypes = ast.literal_eval(row[self.bodysubtype_header])

                        self.route.append([
                            row[self.system_header],
                            row[self.jumps_header],
                            bodynames,
                            bodysubtypes
                        ])
                        self.jumps_left += int(row[self.jumps_header])

            elif headerline == internalfleetcarrierheader:
                self.fleetcarrier = True

                for row in route_reader:
                    if row not in (None, "", []):
                        self.route.append([
                            row[self.system_header],
                            row[self.jumps_header],
                            row[self.restocktritium_header]
                        ])
                        self.jumps_left += int(row[self.jumps_header])

            elif headerline == road2richesimportheader:
                self.roadtoriches = True

                bodynames = []
                bodysubtypes = []

                for row in route_reader:
                    bodyname = row[self.bodyname_header]
                    bodysubtype = row[self.bodysubtype_header]

                    # Update the current system with additional bodies from new CSV row
                    if self.route.__len__() > 0 and row[self.system_header] == self.route[-1][0]:
                        self.route[-1][2].append(bodyname)
                        self.route[-1][3].append(bodysubtype)
                        continue

                    if row not in (None, "", []):
                        bodynames.append(bodyname)
                        bodysubtypes.append(bodysubtype)

                        self.route.append([
                            row[self.system_header],
                            row[self.jumps_header],
                            bodynames.copy(),
                            bodysubtypes.copy()
                        ])
                        # Clear bodies for next system
                        bodynames.clear()
                        bodysubtypes.clear()

                        self.jumps_left += int(row[self.jumps_header])

            elif headerline == fleetcarrierimportheader:
                self.fleetcarrier = True

                for row in route_reader:
                    if row not in (None, "", []):
                        self.route.append([
                            row[self.system_header],
                            1, # Jumps is faked as every row is 1 jump
                            row[self.restocktritium_header]
                        ])
                        self.jumps_left += 1 # Jumps is faked as every row is 1 jump
            elif (headerline == internalgalaxyheader) or (headerline == galaxyimportheader):
                self.galaxy = True

                for row in route_reader:
                    if row not in (None, "", []):
                        self.route.append([
                            row[self.system_header],
                            row[self.refuel_header]
                        ])
                        self.jumps_left += 1
            else:
                self.show_error("Could not detect file format")

    def plot_route(self):
        self.hide_error()
        try:
            source = self.source_ac.get().strip()
            dest = self.dest_ac.get().strip()
            efficiency = self.efficiency_slider.get()

            # Hide autocomplete lists in case they're still shown
            self.source_ac.hide_list()
            self.dest_ac.hide_list()

            if (    source  and source != self.source_ac.placeholder and
                    dest    and dest != self.dest_ac.placeholder    ):

                try:
                    range_ly = float(self.range_entry.get())
                except ValueError:
                    self.show_error("Invalid range")
                    return

                job_url="https://spansh.co.uk/api/route?"

                results = requests.post(job_url, params={
                    "efficiency": efficiency,
                    "range": range_ly,
                    "from": source,
                    "to": dest
                }, headers={'User-Agent': "EDMC_SpanshRouter 1.0"})

                if results.status_code == 202:
                    self.enable_plot_gui(False)

                    tries = 0
                    while(tries < 20):
                        response = json.loads(results.content)
                        job = response["job"]

                        results_url = "https://spansh.co.uk/api/results/" + job
                        route_response = requests.get(results_url, timeout=5)
                        if route_response.status_code != 202:
                            break
                        tries += 1
                        sleep(1)

                    if route_response:
                        if route_response.status_code == 200:
                            route = json.loads(route_response.content)["result"]["system_jumps"]
                            self.clear_route(show_dialog=False)
                            for waypoint in route:
                                self.route.append([waypoint["system"], str(waypoint["jumps"])])
                                self.jumps_left += waypoint["jumps"]
                            self.enable_plot_gui(True)
                            self.show_plot_gui(False)
                            self.offset = 1 if self.route[0][0] == monitor.state['SystemName'] else 0
                            self.next_stop = self.route[self.offset][0]
                            self.copy_waypoint()
                            self.update_gui()
                            self.save_all_route()
                        else:
                            logger.warning(f"Failed to query plotted route from Spansh, code: {str(route_response.status_code)}; text: {route_response.text}")
                            self.enable_plot_gui(True)
                            failure = json.loads(results.content)

                            if route_response.status_code == 400 and "error" in failure:
                                self.show_error(failure["error"])
                                if "starting system" in failure["error"]:
                                    self.source_ac["fg"] = "red"
                                if "finishing system" in failure["error"]:
                                    self.dest_ac["fg"] = "red"
                            else:
                                self.show_error(self.plot_error)
                    else:
                        logger.warning("Query to Spansh timed out")
                        self.enable_plot_gui(True)
                        self.show_error("The query to Spansh was too long and timed out, please try again.")
                else:
                    logger.warning(f"Failed to query plotted route from Spansh: code {str(results.status_code)}; text: {results.text}")
                    self.enable_plot_gui(True)
                    failure = json.loads(results.content)

                    if results.status_code == 400 and "error" in failure:
                        self.show_error(failure["error"])
                        if "starting system" in failure["error"]:
                            self.source_ac["fg"] = "red"
                        if "finishing system" in failure["error"]:
                            self.dest_ac["fg"] = "red"
                    else:
                        self.show_error(self.plot_error)

        except:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
            logger.warning(''.join('!! ' + line for line in lines))
            self.enable_plot_gui(True)
            self.show_error(self.plot_error)

    def plot_edts(self, filename):
        try:
            with open(filename, 'r') as txtfile:
                route_txt = txtfile.readlines()
                self.clear_route(False)
                for row in route_txt:
                    if row not in (None, "", []):
                        if row.lstrip().startswith('==='):
                            jumps = int(re.findall("\d+ jump", row)[0].rstrip(' jumps'))
                            self.jumps_left += jumps

                            system = row[row.find('>') + 1:]
                            if ',' in system:
                                systems = system.split(',')
                                for system in systems:
                                    self.route.append([system.strip(), jumps])
                                    jumps = 1
                                    self.jumps_left += jumps
                            else:
                                self.route.append([system.strip(), jumps])
        except:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
            logger.warning(''.join('!! ' + line for line in lines))
            self.enable_plot_gui(True)
            self.show_error("(2) An error occured while reading the file.")

    def export_route(self):
        if self.route.__len__() == 0:
            logger.info("No route to export")
            return

        route_start = self.route[0][0]
        route_end = self.route[-1][0]
        route_name = f"{route_start} to {route_end}"
        #logger.info(f"Route name: {route_name}")

        ftypes = [('TCE Flight Plan files', '*.exp')]
        filename = filedialog.asksaveasfilename(filetypes = ftypes, initialdir=os.path.expanduser('~'), initialfile=f"{route_name}.exp")

        if filename.__len__() > 0:
            try:
                with open(filename, 'w') as csvfile:
                    for row in self.route:
                        csvfile.write(f"{route_name},{row[0]}\n")
            except:
                exc_type, exc_value, exc_traceback = sys.exc_info()
                lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
                #logger.error(''.join('!! ' + line for line in lines))
                self.show_error("An error occured while writing the file.")

    def clear_route(self, show_dialog=True):
        clear = confirmDialog.askyesno("SpanshRouter","Are you sure you want to clear the current route?") if show_dialog else True

        if clear:
            self.offset = 0
            self.route = []
            self.next_waypoint = ""
            self.jumps_left = 0
            self.roadtoriches = False
            self.fleetcarrier = False
            self.galaxy = False
            try:
                os.remove(self.save_route_path)
            except:
                logger.info("No route to delete")
            try:
                os.remove(self.offset_file_path)
            except:
                logger.info("No offset file to delete")

            self.update_gui()

    def save_all_route(self):
        self.save_route()
        self.save_offset()

    def save_route(self):
        if self.route.__len__() != 0:
            with open(self.save_route_path, 'w', newline='') as csvfile:
                if self.roadtoriches:
                    # Write output: System, Jumps, Bodies[], BodySubTypes[]
                    fieldnames = [self.system_header, self.jumps_header, self.bodyname_header, self.bodysubtype_header]
                    writer = csv.writer(csvfile)
                    writer.writerow(fieldnames)
                    for row in self.route:
                        writer.writerow(row)

                if self.fleetcarrier:
                    # Write output: System, Jumps, 
                    fieldnames = [self.system_header, self.jumps_header, self.restocktritium_header]
                    writer = csv.writer(csvfile)
                    writer.writerow(fieldnames)
                    for row in self.route:
                        writer.writerow(row)

                if self.galaxy:
                    # Write output: System, Refuel
                    fieldnames = [self.system_header, self.refuel_header]
                    writer = csv.writer(csvfile)
                    writer.writerow(fieldnames)
                    writer.writerows(self.route)
                else:
                    # Write output: System, Jumps
                    fieldnames = [self.system_header, self.jumps_header]
                    writer = csv.writer(csvfile)
                    writer.writerow(fieldnames)
                    writer.writerows(self.route)
        else:
            try:
                os.remove(self.save_route_path)
            except:
                logger.info("No route to delete")

    def save_offset(self):
        if self.route.__len__() != 0:
            with open(self.offset_file_path, 'w') as offset_fh:
                offset_fh.write(str(self.offset))
        else:
            try:
                os.remove(self.offset_file_path)
            except:
                logger.info("No offset to delete")

    def update_bodies_text(self):
        if not self.roadtoriches: return

        # For the bodies to scan use the current system, which is one before the next stop
        lastsystemoffset = self.offset - 1
        if lastsystemoffset < 0:
            lastsystemoffset = 0 # Display bodies of the first system

        lastsystem = self.route[lastsystemoffset][0]
        bodynames = self.route[lastsystemoffset][2]
        bodysubtypes = self.route[lastsystemoffset][3]
     
        waterbodies = []
        rockybodies = []
        metalbodies = []
        earthlikebodies = []
        unknownbodies = []

        for num, name in enumerate(bodysubtypes):
            shortbodyname = bodynames[num].replace(lastsystem + " ", "")
            if name.lower() == "high metal content world":
                metalbodies.append(shortbodyname)
            elif name.lower() == "rocky body": 
                rockybodies.append(shortbodyname)
            elif name.lower() == "earth-like world":
                earthlikebodies.append(shortbodyname)
            elif name.lower() == "water world": 
                waterbodies.append(shortbodyname)
            else:
                unknownbodies.append(shortbodyname)

        bodysubtypeandname = ""
        if len(metalbodies) > 0: bodysubtypeandname += f"\n   Metal: " + ', '.join(metalbodies)
        if len(rockybodies) > 0: bodysubtypeandname += f"\n   Rocky: " + ', '.join(rockybodies)
        if len(earthlikebodies) > 0: bodysubtypeandname += f"\n   Earth: " + ', '.join(earthlikebodies)
        if len(waterbodies) > 0: bodysubtypeandname += f"\n   Water: " + ', '.join(waterbodies)
        if len(unknownbodies) > 0: bodysubtypeandname += f"\n   Unknown: " + ', '.join(unknownbodies)

        self.bodies = f"\n{lastsystem}:{bodysubtypeandname}"


    def check_range(self, name, index, mode):
        value = self.range_entry.var.get()
        if value.__len__() > 0 and value != self.range_entry.placeholder:
            try:
                float(value)
                self.range_entry.set_error_style(False)
                self.hide_error()
            except ValueError:
                self.show_error("Invalid range")
                self.range_entry.set_error_style()

    def cleanup_old_version(self):
        try:
            if (os.path.exists(os.path.join(self.plugin_dir, "AutoCompleter.py"))
            and os.path.exists(os.path.join(self.plugin_dir, "SpanshRouter"))):
                files_list = os.listdir(self.plugin_dir)

                for filename in files_list:
                    if (filename != "load.py"
                    and (filename.endswith(".py") or filename.endswith(".pyc") or filename.endswith(".pyo"))):
                        os.remove(os.path.join(self.plugin_dir, filename))
        except:
                exc_type, exc_value, exc_traceback = sys.exc_info()
                lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
                logger.warning(''.join('!! ' + line for line in lines))

    def check_for_update(self):
        return  # Autoupdates is disabled
        self.cleanup_old_version()
        version_url = "https://raw.githubusercontent.com/CMDR-Kiel42/EDMC_SpanshRouter/master/version.json"
        try:
            response = requests.get(version_url, timeout=2)
            if response.status_code == 200:
                if self.plugin_version != response.text:
                    self.update_available = True
                    self.spansh_updater = SpanshUpdater(response.text, self.plugin_dir)

            else:
                logger.warning(f"Could not query latest SpanshRouter version, code: {str(response.status_code)}; text: {response.text}")
        except:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
            logger.warning(''.join('!! ' + line for line in lines))

    def install_update(self):
        self.spansh_updater.install()
