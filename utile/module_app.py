from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import ContentSwitcher, Footer, Header, OptionList
from textual.widgets.option_list import Option

from utile.modules_ui import SECTIONS, build_widget


class WatchFoxApp(App):
    TITLE = "🦊 Watch Fox"
    SUB_TITLE = "Intelligence & Investigation Framework"
    CSS = """
    Screen { background: #0b1220; }
    #menu { width: 36; border: none; background: #0e1628; padding: 0 1; }
    #menu > .option-list--option-disabled { color: #5d7090; text-style: bold; }
    ContentSwitcher { width: 1fr; }
    """
    BINDINGS = [Binding("ctrl+q", "quit", "Quitter"),
                Binding("f5", "run", "Analyser"), Binding("f8", "export", "Exporter"),
                Binding("f9", "reset", "Reset IA")]

    def compose(self) -> ComposeResult:
        yield Header()
        options, self.keys = [], []
        for title, items in SECTIONS:
            options.append(Option(f"── {title} ──", disabled=True))
            for key, label, icon, _ in items:
                options.append(Option(f"{icon} {label}", id=key))
        with Horizontal():
            yield OptionList(*options, id="menu")
            yield ContentSwitcher(id="switcher")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#menu", OptionList).focus()
        self.show("detecteur")

    def show(self, key: str) -> None:
        sw = self.query_one("#switcher", ContentSwitcher)
        wid = f"w_{key}"
        if not sw.query(f"#{wid}"):
            w = build_widget(key)
            w.id = wid
            sw.mount(w)
        sw.current = wid

    @on(OptionList.OptionSelected, "#menu")
    @on(OptionList.OptionHighlighted, "#menu")
    def _select(self, ev) -> None:
        if ev.option.id:
            self.show(ev.option.id)

    def _panel(self):
        sw = self.query_one("#switcher", ContentSwitcher)
        return sw.get_widget_by_id(sw.current) if sw.current else None

    def action_run(self):
        p = self._panel()
        getattr(p, "action_analyse", lambda: None)()

    def action_export(self):
        p = self._panel()
        getattr(p, "action_export", lambda: None)()

    def action_reset(self):
        p = self._panel()
        getattr(p, "action_reset", lambda: None)()


if __name__ == "__main__":
    WatchFoxApp().run()