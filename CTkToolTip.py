# CTkToolTip.py
import tkinter as tk
from typing import Union

class CTkToolTip:
    """
    Creates a tooltip for a given customtkinter widget.
    """
    def __init__(
            self,
            widget: any,
            message: str,
            delay: float = 0.5,
            follow: bool = True,
            x_offset: int = +20,
            y_offset: int = +10,
            bg_color: Union[str, None] = None,
            fg_color: str = "white",
            corner_radius: int = 6,
            border_width: int = 1,
            border_color: Union[str, None] = None,
            alpha: float = 0.9,
            padding: tuple = (10, 5)):

        self.widget = widget
        self.message = message
        self.delay = delay
        self.follow = follow
        self.x_offset = x_offset
        self.y_offset = y_offset
        self.bg_color = "#242424" if bg_color is None else self.widget.cget("fg_color") if bg_color == "widget" else bg_color
        self.fg_color = fg_color
        self.corner_radius = corner_radius
        self.border_width = border_width
        self.border_color = border_color
        self.alpha = alpha
        self.padding = padding
        self.font = self.widget.cget("font")
        
        self.tip_window = None
        self.id = None
        
        self.widget.bind("<Enter>", self.schedule_tip, add="+")
        self.widget.bind("<Leave>", self.hide_tip, add="+")
        self.widget.bind("<ButtonPress>", self.hide_tip, add="+")
        
    def schedule_tip(self, event=None):
        """ Schedule the tooltip to appear after the delay """
        if self.tip_window:
            return
        self.id = self.widget.after(int(self.delay * 1000), self.show_tip)

    def show_tip(self):
        """ Create and show the tooltip """
        if self.tip_window:
            return

        # Get the position of the widget
        x = self.widget.winfo_rootx() + self.x_offset
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + self.y_offset
        
        self.tip_window = tk.Toplevel(self.widget)
        self.tip_window.wm_overrideredirect(True)
        self.tip_window.wm_geometry(f"+{x}+{y}")
        self.tip_window.wm_attributes("-alpha", self.alpha)

        if self.corner_radius > 0:
            self.tip_window.config(background=self.bg_color)
            self.tip_window.wm_attributes("-transparentcolor", self.bg_color)

        frame = tk.Frame(self.tip_window, background=self.bg_color, highlightbackground=self.border_color,
                         highlightcolor=self.border_color, highlightthickness=self.border_width, relief="solid")
        frame.pack(expand=True, fill="both")

        label = tk.Label(frame, text=self.message, justify="left",
                         background=self.bg_color, foreground=self.fg_color,
                         font=self.font,
                         padx=self.padding[0], pady=self.padding[1])
        label.pack()

        if self.follow:
            self.widget.bind("<Motion>", self.move_tip, add="+")

    def move_tip(self, event=None):
        """ Move the tooltip to follow the mouse """
        if not self.tip_window:
            return

        x = self.widget.winfo_rootx() + self.x_offset
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + self.y_offset
        self.tip_window.wm_geometry(f"+{x}+{y}")
        
    def hide_tip(self, event=None):
        """ Hide and destroy the tooltip """
        if self.id:
            self.widget.after_cancel(self.id)
            self.id = None
        
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None

        self.widget.unbind("<Motion>")

    def set_message(self, message: str):
        self.message = message