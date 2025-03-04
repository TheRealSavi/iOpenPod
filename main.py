import json
import dearpygui.dearpygui as dpg


from iTunesDB_Parser.parser import parse_itunesdb

#Debug UI
dpg.create_context()

with dpg.font_registry():
    large_font = dpg.add_font("C:/Windows/Fonts/arial.ttf", 24)
dpg.bind_font(large_font)

with dpg.window(label="iOpenPod iTunesDB Parser", width=600, height=600):
    logWindowParse = dpg.add_text("Logs:\n")
    
def log_message(message):
    dpg.set_value(logWindowParse, f"{dpg.get_value(logWindowParse)}\n{message}")


def start_parsing():
    result = parse_itunesdb(r"C:\Users\JohnG\Documents\Coding Projects\iOpenPod\iOpenPod\iTunesDB")
    print(str(result))
    with open("data.json", "w") as f:
        json.dump(result, f, indent=2)

#UI
with dpg.window(label="Controls", pos=(10, 450)):
    dpg.add_button(label="Start Parsing", callback=start_parsing)

dpg.create_viewport(title="iOpenPod", width=650, height=650)
dpg.setup_dearpygui()
dpg.show_viewport()
dpg.start_dearpygui()
dpg.destroy_context()
