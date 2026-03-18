#!/usr/bin/env python3
"""Display runner for the Lian Li LANCOOL 207 Digital LCD.

Commands:
  repeat     -- Show a message on the LCD repeatedly
  dictionary -- Show random esoteric words on the LCD
"""

from __future__ import annotations

import argparse
import random
import time
from typing import Dict, List, Optional

from display_driver import DisplayDriver, make_driver, show_text


ESOTERIC_WORDS: Dict[str, str] = {
    "abecedarian": "A person who is learning the alphabet; someone very inexperienced.",
    "cymotrichous": "Having wavy hair.",
    "defenestrate": "To throw someone or something out of a window.",
    "eschatology": "The part of theology concerned with death, judgment, and the final destiny of the soul.",
    "floccinaucinihilipilification": "The act of estimating something as worthless.",
    "gargalesthesia": "The sensation produced by tickling.",
    "hiraeth": "A homesickness for a home to which you cannot return; nostalgia.",
    "ineffable": "Too great or extreme to be expressed or described in words.",
    "juxtaposition": "The fact of two things being seen or placed close together with contrasting effect.",
    "knismesis": "A light, tickling sensation.",
    "limerence": "The state of being infatuated with another person.",
    "mnemonic": "A device such as a pattern of letters used to aid memory.",
    "nemophilist": "One who loves the woods or forest; a haunter of the woods.",
    "obfuscate": "Render obscure, unclear, or unintelligible.",
    "palimpsest": "Something reused or altered but still bearing visible traces of its earlier form.",
    "querencia": "A place where one feels safe, a place from which one's strength is drawn.",
    "recumbentibus": "A knockout punch, either verbal or physical.",
    "susurrus": "A whispering or rustling sound.",
    "threnody": "A lament, especially a song or poem of mourning.",
    "ultracrepidarian": "Someone who gives opinions on subjects they know nothing about.",
    "venustraphobia": "Fear of beautiful women.",
    "wyrd": "Fate or personal destiny.",
    "xenization": "The act of traveling as a stranger.",
    "yugen": "A profound, mysterious sense of the beauty of the universe.",
    "zoanthropy": "A delusion that one is an animal.",
}


def run_repeat(text: str, interval: float, driver: Optional[DisplayDriver] = None) -> None:
    if driver is None:
        driver = make_driver()

    try:
        while True:
            show_text(text, driver=driver)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("Stopped repeating.")


def run_dictionary(interval: float, driver: Optional[DisplayDriver] = None) -> None:
    if driver is None:
        driver = make_driver()

    try:
        while True:
            word, definition = random.choice(list(ESOTERIC_WORDS.items()))
            show_text(f"{word}\n{definition}", driver=driver)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("Stopped dictionary mode.")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Drive the Lian Li LANCOOL 207 Digital LCD.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    rep = sub.add_parser("repeat", help="Repeat a message on the LCD.")
    rep.add_argument("--text", required=True, help="Text to display.")
    rep.add_argument("--interval", type=float, default=2.0, help="Seconds between updates.")

    dictp = sub.add_parser("dictionary", help="Show random esoteric words on the LCD.")
    dictp.add_argument("--interval", type=float, default=3.0, help="Seconds between words.")

    args = parser.parse_args(argv)
    driver = make_driver()

    if args.cmd == "repeat":
        run_repeat(args.text, args.interval, driver=driver)
    elif args.cmd == "dictionary":
        run_dictionary(args.interval, driver=driver)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
