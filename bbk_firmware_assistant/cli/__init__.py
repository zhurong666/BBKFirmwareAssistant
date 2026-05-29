from __future__ import annotations

from ._common import ask_select
from .download import flow_download
from .extract import flow_extract
from .flash import flow_flash

ACTIONS = {
    "Download OTA firmware": flow_download,
    "Extract OTA firmware": flow_extract,
    "Flash firmware": flow_flash,
}


def main() -> None:
    while True:
        choice = ask_select("Action:", [*ACTIONS, "Quit"])
        if not choice or choice == "Quit":
            break
        try:
            ACTIONS[choice]()
        except KeyboardInterrupt:
            print("  (interrupted)")