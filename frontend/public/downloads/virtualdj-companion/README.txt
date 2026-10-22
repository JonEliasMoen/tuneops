TuneOps VirtualDJ companion
===========================

Requirements
------------
- Windows with VirtualDJ
- Python 3.10 or newer
- TIDAL tracks played through VirtualDJ's TIDAL extension

Workflow
--------
1. Open a collection in TuneOps and click "Export VirtualDJ metadata".
2. Download tuneops_virtualdj.py from TuneOps Settings (only needed once).
3. Preview the changes while VirtualDJ can remain open:

   python tuneops_virtualdj.py "My-playlist-virtualdj-metadata.json"

4. Close VirtualDJ completely.
5. Apply the changes:

   python tuneops_virtualdj.py "My-playlist-virtualdj-metadata.json" --apply

The normal database location is detected automatically. To use another file:

   python tuneops_virtualdj.py metadata.json --database "D:\VirtualDJ\database.xml" --apply

Safety and behavior
-------------------
- Preview is the default; writing requires the explicit --apply flag.
- A timestamped backup is created beside database.xml before every write.
- The generated XML is parsed and validated before it replaces database.xml.
- Tracks match only by the exact numeric TIDAL ID in netsearch://td<ID> or
  Link NetSearch="td<ID>". Titles and artist names are never guessed.
- Existing comments and other metadata are preserved. TuneOps writes the native
  VirtualDJ star rating on the existing Tags element, for example Stars="5".
- A valid four-digit release year is written to the native Tags Year attribute.
- All non-rating dimensions and free-form tags are written as one managed
  Comment line. Spaces and punctuation collapse into searchable hashtags:

  [TuneOps] #Energy4 #Tension3 #Dark #Hypnotic #VibeFlip #LeadAcid

  Rerunning replaces only that line and preserves other comment text.

- The JSON contains every selected collection track plus all typed TuneOps
  dimensions and free-form tags. The companion applies non-empty native star
  ratings and the managed TuneOps hashtag line. It never clears a VirtualDJ
  rating.
- The companion never creates missing Song records. If a TIDAL playlist is only
  present in VirtualDJ's provider cache, batch-edit/tag those tracks in
  VirtualDJ first so VirtualDJ materializes valid database.xml records.
