"""Technical copy and heading treatment for the presenter's four workshop sections."""
import html
import json
import pathlib
import re

SCOPED_SECTIONS = {'fund', 'disagg', 'auto', 'adm'}


def apply(built, program):
    config = json.loads(pathlib.Path(__file__).with_suffix('.json').read_text())
    for e in config['replacements']:
        slide = built[e['deck']]['slides'][e['index']]
        count = slide.count(e['old'])
        if not count:
            raise ValueError(f"Copy target not found on slide {e['slide']}: {e['old']}")
        built[e['deck']]['slides'][e['index']] = slide.replace(e['old'], e['new'])
    notes = json.loads(pathlib.Path(__file__).with_name('presenter_notes.json').read_text())
    for e in config['titles']:
        slide = built[e['deck']]['slides'][e['index']]
        old_title = re.search(r'data-title="([^"]*)"', slide)
        if old_title:
            slide = slide.replace('<section ', '<section data-original-title="'+old_title[1]+'" ', 1)
            built[e['deck']]['js'] = built[e['deck']]['js'].replace('[data-title="'+old_title[1]+'"]', '[data-title="'+e['title']+'"]')
        # One technical heading per slide; drop imported section labels and act bars.
        slide = re.sub(r'<(div|span) class="(?:kicker|eyebrow|actbar)"[^>]*>.*?</\1>', '', slide, flags=re.S)
        slide, n = re.subn(r'(<h[12]\b[^>]*>).*?(</h[12]>)', lambda m: m[1]+html.escape(e['title'])+m[2], slide, count=1, flags=re.S)
        if n != 1:
            raise ValueError(f"Heading not found on slide {e['slide']}")
        slide, n = re.subn(r'\bdata-title="[^"]*"', lambda _: 'data-title="'+html.escape(e['title'],quote=True)+'"', slide, count=1)
        if n != 1:
            slide = slide.replace('<section ', '<section data-title="'+html.escape(e['title'],quote=True)+'" ', 1)
        note = notes.get(f"{e['deck']}:{e['index']}")
        if note:
            aside = '<aside class="notes">'+note+'</aside>'
            if re.search(r'<aside class="notes"[^>]*>',slide):
                slide = re.sub(r'<aside class="notes"[^>]*>.*?</aside>',lambda _:aside,slide,flags=re.S)
            else:
                slide=slide.replace('</section>',aside+'</section>')
        built[e['deck']]['slides'][e['index']] = slide
    js = built['router']['js']
    js = js.replace('s.dataset.title === t', '(s.dataset.originalTitle || s.dataset.title) === t')
    js = js.replace("notes: i => NOTES[all[i].dataset.title] || ''", "notes: i => all[i].querySelector('aside.notes')?.innerHTML || NOTES[all[i].dataset.originalTitle || all[i].dataset.title] || ''")
    built['router']['js'] = js
    # Keep the imported next-slide labels aligned with the new headings.
    for section in program:
        if section['id'] not in SCOPED_SECTIONS:
            continue
        entries=[]
        for deck, indexes in section['slides']:
            entries += [(deck,i) for i in (range(len(built[deck]['slides'])) if indexes=='*' else indexes)]
        for position,(deck,index) in enumerate(entries):
            if deck!='router':
                continue
            following=entries[position+1] if position+1<len(entries) else None
            text=''
            if following:
                nxt=built[following[0]]['slides'][following[1]]
                text=re.search(r'data-title="([^"]*)"',nxt)[1]
            built[deck]['slides'][index] = re.sub(r'\sdata-next="[^"]*"','',built[deck]['slides'][index],count=1)
            if text:
                built[deck]['slides'][index]=built[deck]['slides'][index].replace('<section ','<section data-next="'+text+'" ',1)
