#!/usr/bin/env python3
"""One-slide VP brief: an incentive program to scale Project Pulse evaluations."""
import os
from pptx.util import Inches, Pt, Emu
from pptx.enum.text import PP_ALIGN
from pptx.enum.shapes import MSO_SHAPE
from build_decks import (new_deck, blank, four_bar, rect, text, para, kicker,
                         HEAD, BODY, BLUE, RED, YELLOW, GREEN, G900, G700, G500,
                         G200, G050, WHITE, INK, FOUR)

HERE = os.path.dirname(os.path.abspath(__file__))


def card(s, x, y, w, h, accent, title, items):
    c = rect(s, x, y, w, h, G050, line=G200, line_w=Pt(0.75),
             shape=MSO_SHAPE.ROUNDED_RECTANGLE)
    try: c.adjustments[0] = 0.04
    except Exception: pass
    rect(s, x, y, w, Inches(0.09), accent)
    _, tf = text(s, Emu(int(x)+Emu(0.28*914400)), Emu(int(y)+Emu(0.24*914400)),
                 Emu(int(w)-Emu(0.55*914400)), Inches(0.5),
                 [(title, {"bold": True, "color": G900, "size": 16, "font": HEAD})])
    for it in items:
        para(tf, it, size=12.7, color=G700, font=BODY, space_before=9,
             bullet="●", bullet_color=accent, line_spc=1.08)


def build():
    prs = new_deck()
    s = blank(prs)
    four_bar(s)

    kicker(s, Inches(0.6), Inches(0.42), "Proposal for VP · Project Pulse")
    text(s, Inches(0.6), Inches(0.8), Inches(12.1), Inches(0.7),
         "Make model evaluation a team sport", size=31, bold=True,
         color=G900, font=HEAD)
    text(s, Inches(0.6), Inches(1.55), Inches(12.1), Inches(0.6),
         [("The ask:  ", {"bold": True, "color": BLUE, "size": 15, "font": HEAD}),
          ("run a one-quarter incentive program that rewards our top blind-vote evaluators "
           "with a spot bonus — turning Project Pulse into defensible, customer-ready model data.",
           {"color": G700, "size": 15})],
         line_spc=1.15)

    cy = Inches(2.3); ch = Inches(3.1)
    cw = Inches(3.9); gap = Inches(0.22); x0 = Inches(0.6)
    card(s, x0, cy, cw, ch, BLUE, "The program (“Pulse MVR”)",
         ["Monthly Eval Sprint — blind A/B rating across video, image & TTS.",
          "Every vote auto-tagged by use-case → live Win-Rate-by-Tag leaderboard.",
          "Top raters win a monthly spot bonus — ranked on volume × quality, "
          "with anti-gaming via consensus + the AI judge."])
    card(s, Emu(int(x0)+int(cw)+int(gap)), cy, cw, ch, GREEN, "Why it earns buy-in",
         ["More votes → defensible model calls in customer POCs → Vertex consumption.",
          "Bonus pool ≪ the cost of one wrong model pick in a live deal.",
          "Rallies the field around GenAI and builds a compounding data asset."])
    card(s, Emu(int(x0)+2*(int(cw)+int(gap))), cy, cw, ch, YELLOW, "What I need from you",
         ["Endorse a 1-quarter pilot + a short kickoff note from you.",
          "Approve a small monthly spot-bonus pool (e.g. top 3).",
          "Give it airtime as a team OKR — I run it and report monthly."])

    # bottom band — metrics + guardrails
    band = rect(s, Inches(0.6), Inches(5.6), Inches(12.13), Inches(1.15),
                RGBColor_lite(), shape=MSO_SHAPE.ROUNDED_RECTANGLE)
    try: band.adjustments[0] = 0.10
    except Exception: pass
    _, tf = text(s, Inches(0.95), Inches(5.74), Inches(11.4), Inches(0.9),
                 [("Measure of success (90 days):  ",
                   {"bold": True, "color": BLUE, "size": 13.5, "font": HEAD}),
                  ("votes/week · active raters · tag coverage · # POCs citing Pulse data.",
                   {"color": G900, "size": 13.5})], line_spc=1.12)
    para(tf, [("Low cost · quality-gated · fully reversible.  ",
               {"bold": True, "color": G700, "size": 12, "font": HEAD}),
              ("Bonus mechanics to be aligned with HR/Comp before launch.",
               {"color": G700, "size": 12})], space_before=5)

    # footer
    text(s, Inches(0.6), Inches(7.06), Inches(9), Inches(0.3),
         "GenMedia SxS · Project Pulse — evaluator incentive proposal",
         size=9, color=G500, font=BODY)
    rect(s, Inches(0.6), Inches(7.02), Inches(12.13), Pt(0.75), G200)

    out = os.path.join(HERE, "GenMedia SxS - VP Brief (Evaluator Program).pptx")
    prs.save(out)
    print("saved", out, "slides:", len(prs.slides._sldIdLst))
    return out


def RGBColor_lite():
    from pptx.dml.color import RGBColor
    return RGBColor(0xE8, 0xF0, 0xFE)  # Google blue tint


if __name__ == "__main__":
    build()
