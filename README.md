# OMP FOO session: pitch and deck

- `PITCH.md`: session-board card, short pitches, run of show, claim sources.
- `deck.html`: the built deck. Open it in a browser; it works offline. Press N for notes.
- `deck.template.html`: edit this, then run `python3 build.py` to rebuild `deck.html`.
- `sample/`: the OMP export the deck embeds. Edit `sample/build_sample.py`, then run it to regenerate `manifest.json`, `memories.json` and checksums.

```sh
python3 sample/build_sample.py && python3 build.py
```
