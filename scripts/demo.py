#!/usr/bin/env python3
"""Build the public desktop illustration with real Fenlet UI and layout geometry."""
import argparse
import html
import json
import os
from pathlib import Path
import runpy
import select
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fenlet.core import build_actions
from fenlet.overlap import analyze_overlaps

PROJECT = ROOT / "build/fenlet-demo"
HYPERFRAMES = ["npx", "--yes", "hyperframes@0.9.19"]


def fixture():
    def screen(id, name, x, y, width, height, mm, built_in=False):
        return dict(id=id, name=name, built_in=built_in, bounds=dict(x=x,y=y,width=width,height=height),
                    usable=dict(x=x,y=y+30,width=width,height=height-60), physical_size_mm=dict(width=mm[0],height=mm[1]))
    screens = [screen("work", "Work display", 0, 0, 2560, 1440, (598,336)),
               screen("laptop", "Laptop", 2560, 330, 1512, 982, (301,196), True)]
    rows = [
        ("terminal", "Terminal", "garden · main", (70,110,1420,1000), "work"),
        ("code", "TextEdit", "layout.py", (680,90,1200,1070), "work"),
        ("reference", "Notes", "Keyboard shortcuts", (1450,270,850,980), "laptop"),
        ("music", "Music", "Focus mix", (150,830,850,550), "minimize"),
        ("calendar", "Calendar", "This week", (2770,390,1040,700), "minimize"),
        ("scratch", "Notes", "Untitled", (1490,780,1000,550), "close"),
        ("newtab", "Safari", "New Tab", (170,360,1280,740), "close"),
        ("chat", "Messages", "Team chat", (1610,130,850,930), "laptop"),
        ("browser", "Safari", "Project notebook", (540,390,1380,920), "work"),
    ]
    windows, decisions = [], []
    for id, app, title, bounds, role in rows:
        windows.append(dict(id=id,app_name=app,title=title,pid=100,process_instance="synthetic-public-demo",
                            accessible=True,minimized=False,is_focused=id=="terminal",
                            bounds=dict(zip(("x","y","width","height"), bounds))))
        decisions.append(dict(id=id,role=role if role in ("minimize","close") else "display_"+role))
    inventory = dict(displays=screens,windows=windows,created_at=0,scan_ms=0,coverage=dict(complete=True,errors=[]))
    actions = build_actions(inventory, decisions)
    assert {kind:sum(a["kind"]==kind for a in actions) for kind in ("move","minimize","close")} == dict(move=5,minimize=2,close=2)
    for display in screens:
        panes=[a["target"] for a in actions if a["kind"]=="move" and a["display"]==display["id"]]
        assert analyze_overlaps(panes).count == 0
    return dict(plan_path="synthetic",plan=dict(inventory=inventory,actions=actions),window_count=9,action_count=9,
                model=None,coverage=dict(errors=[]))


def capture_widgets(preview):
    harness = runpy.run_path(str(ROOT / "scripts/verify-widget.py"))
    assets = PROJECT / "assets"
    with tempfile.TemporaryDirectory(prefix="fenlet-promo-ui-") as temporary:
        directory=Path(temporary); executable=directory/"FenletPromoFixture"
        (directory/"bin").mkdir()
        # The native UI can render seeded state, never scan the user's desktop or call a provider.
        cli=directory/"bin/fenlet"
        cli.write_text('#!/bin/sh\nprintf \'%s\\n\' \'{"ok":false,"error":"Synthetic documentation fixture: commands are disabled."}\'\nexit 1\n')
        cli.chmod(0o700)
        harness["build_fixture"](executable)
        input_path=directory/"input.json"; input_path.write_text(json.dumps(preview))
        env={**os.environ,"FENLET_CONFIG":str(directory/"config.json"),"FENLET_STATE":str(directory/"state")}
        buttons={}
        for state,flag,label in (("live","--demo-live","Arrange windows"),("draft","--demo","Confirm arrangement")):
            process=subprocess.Popen([str(executable),str(input_path),flag,"--export-icons",str(assets)],stdout=subprocess.PIPE,text=True,env=env)
            try:
                if not select.select([process.stdout],[],[],15)[0]: raise TimeoutError("Native demo fixture did not open")
                window=int(process.stdout.readline()); data=harness["snapshot"](window)
                elements=data["ui_elements"]
                frame=next(e["bounds"] for e in elements if e.get("ax_role")=="AXWindow")
                button=next(e["bounds"] for e in elements if e.get("label")==label)
                assert button["y"]+button["height"] <= frame["y"]+frame["height"]
                buttons[state]=dict(x=button["x"]-frame["x"]+button["width"]*.7,
                                    y=button["y"]-frame["y"]+button["height"]*.5)
                response=json.loads(subprocess.check_output(["peekaboo","see","--window-id",str(window),"--no-elements","--retina",
                                      "--path",str(assets/f"widget-{state}.png"),"--json"],text=True))
                assert response.get("success"),response.get("error")
            finally:
                if process.poll() is None: process.terminate()
                process.wait(timeout=3); process.stdout.close()
    (assets/"widget-buttons.json").write_text(json.dumps(buttons,indent=2)+"\n")
    return buttons


CONTENTS = {
    "terminal": '''<pre><span class="green">mila</span> <span class="blue">~/projects/garden</span>\n<span class="dim">main</span> % npm run dev\n\n<span class="dim">&gt; garden@1.4.0 dev\n&gt; vite</span>\n\n<span class="green">  VITE ready</span>\n\n  Local: <span class="blue">localhost:5173</span>\n\n<span class="green">✓</span> Navigation\n<span class="green">✓</span> Keyboard shortcuts\n<span class="green">✓</span> Window layout\n\n<span class="dim">All checks passed.</span>\n\n<span class="green">mila</span> % ▍</pre>''',
    "browser": '''<div class="crumb">Garden / Project notes</div><h2>A little more<br>breathing room.</h2><p class="muted">Make the useful things easy to find.</p><div class="document-rule"></div><h3>Today’s focus</h3><div class="checkline"><b>✓</b><span>Finish the new navigation</span></div><div class="checkline"><b>✓</b><span>Review keyboard shortcuts</span></div><div class="checkline"><b>○</b><span>Ship the first preview</span></div><div class="note-callout">Keep the browser beside the terminal.<br>One thought at a time.</div><h3>For the next pass</h3><p class="muted">A calmer homepage.<br>Less work between you and your work.</p>''',
    "code": '''<div class="code-tabs">layout.py</div><pre><span class="comment"># Give every window a place.</span>\n\n<span class="keyword">def</span> arrange_workspace(\n    windows, displays\n):\n    groups = group_by_display(\n        windows, displays\n    )\n\n    <span class="keyword">for</span> screen, panes <span class="keyword">in</span> groups:\n        layout = pack_columns(\n            screen, panes\n        )\n        <span class="keyword">yield from</span> layout\n\n\n<span class="comment"># Keep the useful things close.</span>\npreferences = {\n    <span class="string">"work"</span>: <span class="string">"big screen"</span>,\n    <span class="string">"chat"</span>: <span class="string">"laptop"</span>,\n    <span class="string">"gaps"</span>: 6,\n}</pre>''',
    "chat": '''<h2>Team chat</h2><div class="chat-date">Today</div><div class="bubble"><b>Mila</b>The notes are ready for a look.</div><div class="bubble me">Perfect. I’ve got them right here.</div><div class="bubble"><b>Sam</b>I’ll review the build after lunch.</div><div class="message-field">Message</div>''',
    "reference": '''<div class="crumb">Reference</div><h2>Keyboard shortcuts</h2><div class="shortcut"><span>Switch apps</span><b>⌘ Tab</b></div><div class="shortcut"><span>Quick search</span><b>⌘ Space</b></div><div class="shortcut"><span>New tab</span><b>⌘ T</b></div><div class="shortcut"><span>Find</span><b>⌘ F</b></div>''',
    "music": '''<div class="album"></div><h2>Focus mix</h2><p>A little room to think</p><div class="playback">‹ Ⅱ ›</div>''',
    "scratch": '''<h2>Untitled</h2><p>Maybe later…</p><p>old ideas<br>one more tab<br>where did that window go?</p>''',
    "newtab": '''<h2>Start Page</h2><div class="search">Search or enter a website</div>''',
    "calendar": '''<div class="crumb">November</div><div class="day">05</div><div class="event">10:00　Design review</div><div class="event">12:30　Lunch</div><div class="event">15:00　A quiet hour</div>''',
}


def window_markup(window,id,width,height):
    kind=window["id"]
    category={"browser":"document","code":"code","terminal":"terminal","chat":"chat","reference":"reference"}.get(kind,kind)
    icon="icon-"+window["app_name"].lower()+".png"
    assert (PROJECT/"assets"/icon).is_file(),icon
    return f'''<div id="{id}" class="window {category}" style="width:{width:.3f}px;height:{height:.3f}px" data-layout-allow-occlusion data-layout-allow-overlap>
      <div class="window-title" data-layout-ignore><span class="lights"><i></i><i></i><i></i></span><img class="app-icon" src="assets/{icon}" alt=""><span>{html.escape(window["title"])}</span></div>
      <div class="window-body" data-layout-ignore>{CONTENTS[kind]}</div></div>'''


def prepare_scene(preview, buttons):
    inventory=preview["plan"]["inventory"]
    screens={s["id"]:s for s in inventory["displays"]}
    sizes={"work":(1240,613),"laptop":(372,232)}
    def mapped(frame, display):
        usable=screens[display]["usable"]; width,height=sizes[display]
        return dict(x=(frame["x"]-usable["x"])*width/usable["width"],y=(frame["y"]-usable["y"])*height/usable["height"],
                    width=frame["width"]*width/usable["width"],height=frame["height"]*height/usable["height"])
    markup={"work":[],"laptop":[]}; tweens=[]
    for index,action in enumerate(preview["plan"]["actions"]):
        window=action["window"]; id="win-"+window["id"]
        current="laptop" if window["id"]=="calendar" else "work"
        before=mapped(window["bounds"],current)
        display=action.get("display",current)
        after=mapped(action["target"],display) if action["kind"]=="move" else before
        same=display==current
        base=after if same else before
        markup[current].append(window_markup(window,id,base["width"],base["height"]))
        start=dict(x=before["x"],y=before["y"],scaleX=before["width"]/base["width"],scaleY=before["height"]/base["height"],opacity=1)
        end=dict(duration=.8,ease="power3.inOut")
        at=6.25+(index%3)*.04
        if action["kind"]=="close": end.update(x=before["x"],y=before["y"]+12,scaleX=.96,scaleY=.96,opacity=0,duration=.23)
        elif action["kind"]=="minimize": end.update(x=500 if current=="work" else 180,y=635 if current=="work" else 240,scaleX=.02,scaleY=.02,opacity=0,duration=.5)
        elif same: end.update(x=after["x"],y=after["y"],scaleX=1,scaleY=1)
        else:
            end.update(x=1100,y=before["y"]+90,scaleX=.45,scaleY=.45,opacity=0,duration=.55)
            arrived=id+"-arrived"; markup[display].append(window_markup(window,arrived,after["width"],after["height"]))
            tweens.append(f"tl.fromTo('#{arrived}', {json.dumps(dict(x=after['x']-15,y=after['y']+10,opacity=0,scaleX=.96,scaleY=.96))}, {json.dumps(dict(x=after['x'],y=after['y'],opacity=1,scaleX=1,scaleY=1,duration=.4,ease='power3.out'))}, 6.8);")
        tweens.append(f"tl.fromTo('#{id}', {json.dumps(start)}, {json.dumps(end)}, {at:.2f});")
    # Positions come from Accessibility bounds on the real native buttons.
    points={key:dict(x=984+value["x"]*2,y=180+value["y"]*2-(100 if key=="live" else 180)) for key,value in buttons.items()}
    a,b=points["live"],points["draft"]
    cursor=f'''tl.fromTo('#pointer', {{x:1860,y:900,opacity:0}}, {{x:{a['x']-17},y:{a['y']-10},opacity:1,duration:.75,ease:'power3.out'}}, 1.9);
    tl.to('#pointer', {{scale:.87,duration:.09}}, 3.06); tl.to('#pointer', {{scale:1,duration:.12}}, 3.15);
    tl.to('#pointer', {{x:{b['x']-17},y:{b['y']-10},duration:.48,ease:'power3.inOut'}}, 4.75);
    tl.to('#pointer', {{scale:.87,duration:.09}}, 6.16); tl.to('#pointer', {{scale:1,duration:.12}}, 6.25);
    tl.to('#pointer', {{x:1850,y:900,opacity:0,duration:.4}}, 6.4);
    tl.fromTo('#press-one', {{x:{a['x']-33},y:{a['y']-33},scale:.3,opacity:0}}, {{scale:1,opacity:.7,duration:.12}}, 3.1);
    tl.to('#press-one', {{scale:1.25,opacity:0,duration:.3}}, 3.22);
    tl.fromTo('#press-two', {{x:{b['x']-33},y:{b['y']-33},scale:.3,opacity:0}}, {{scale:1,opacity:.7,duration:.12}}, 6.2);
    tl.to('#press-two', {{scale:1.25,opacity:0,duration:.3}}, 6.32);'''
    source=(ROOT/"media/fenlet-demo/compositions/workspace.html").read_text()
    replacements={"@@WORK_WINDOWS@@":"\n".join(markup["work"]),"@@LAPTOP_WINDOWS@@":"\n".join(markup["laptop"]),
                  "@@WINDOW_TWEENS@@":"\n".join(tweens),"@@CURSOR_TWEENS@@":cursor,
                  "@@DOCK@@":"".join(f'<img src="assets/icon-{app}.png" alt="">' for app in ("terminal","safari","textedit","messages","notes","music","calendar"))}
    for key,value in replacements.items(): source=source.replace(key,value)
    assert "@@" not in source
    (PROJECT/"compositions/workspace.html").write_text(source)
    (PROJECT/"assets/layout.json").write_text(json.dumps(preview,indent=2)+"\n")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=ROOT/"docs")
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument("--prepare-only",action="store_true")
    mode.add_argument("--render-only",action="store_true")
    parser.add_argument("--reuse-captures",action="store_true")
    args=parser.parse_args(); args.output=args.output.expanduser().resolve()
    args.output.mkdir(parents=True,exist_ok=True)
    if not args.render_only:
        (PROJECT/"assets").mkdir(parents=True,exist_ok=True);(PROJECT/"compositions").mkdir(exist_ok=True)
        for name in ("index.html","hyperframes.json","package.json"):
            shutil.copy2(ROOT/"media/fenlet-demo"/name,PROJECT/name)
        shutil.copy2(ROOT/"assets/fenlet.svg",PROJECT/"assets/fenlet.svg")
        preview=fixture()
        buttons=json.loads((PROJECT/"assets/widget-buttons.json").read_text()) if args.reuse_captures else capture_widgets(preview)
        prepare_scene(preview,buttons)
    if args.prepare_only:
        print(json.dumps(dict(project=str(PROJECT),synthetic=True,arranged=5,minimized=2,closed=2,model_calls=0,user_window_operations=0)));return
    subprocess.run(HYPERFRAMES+["check","--json"],cwd=PROJECT,check=True)
    with tempfile.TemporaryDirectory(prefix="fenlet-poster-") as temporary:
        subprocess.run(HYPERFRAMES+["snapshot","--at","9.5","--no-end","--output",temporary,"--json"],cwd=PROJECT,check=True)
        posters=list(Path(temporary).glob("frame-*.png")); assert len(posters)==1
        shutil.copy2(posters[0],args.output/"preview.png")
    subprocess.run(HYPERFRAMES+["render","--quality","delivery","--output",str(args.output/"demo.mp4")],cwd=PROJECT,check=True)
    subprocess.run(["ffmpeg","-y","-loglevel","error","-i",str(args.output/"demo.mp4"),"-filter_complex",
        "fps=15,scale=1200:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=160:stats_mode=diff[p];[b][p]paletteuse=dither=sierra2_4a:diff_mode=rectangle",
        "-loop","0",str(args.output/"demo.gif")],check=True)
    print(json.dumps(dict(synthetic=True,seconds=12,model_calls=0,user_window_operations=0,output=str(args.output))))


if __name__=="__main__": main()
