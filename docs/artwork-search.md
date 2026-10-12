# Finding album artwork

1. Right-click one Music Album and choose **Find Album Artwork… → iTunes Store…**
   or **Discogs…**. A complete Album selection in a Track table offers the same action.
2. Edit the artist and album search terms if needed. For iTunes Store, enter a
   two-letter store region such as `US`, `GB`, or `JP`. For Discogs, paste a personal
   access token from [developer settings](https://www.discogs.com/settings/developers).
   The dialog keeps the token only until it closes.
3. Click **Search** and choose a result to load its cover. The preview shows the
   downloaded image's actual dimensions. **Open Album Page** opens the provider's
   listing in your browser.
4. Choose **Apply Artwork**. **Apply only to tracks without artwork** starts checked
   if any Album Tracks lack an artwork assignment. Uncheck it to replace covers
   across the whole Album. Existing later timed images are preserved.

Artwork follows the same save policy as other Library edits: automatic saving by
default, or manual review and save with **Draft all changes** enabled. Cancelling
the dialog leaves the Library untouched. If the Library changes or the iPod
disconnects, reopen the action to use the current selection.

You can also open **Edit Metadata… → Artwork** and click **Find Album Artwork…**.
This works for the selected Tracks, including a single Track. Search iTunes Store
or Discogs, preview a result, and choose **Use Artwork** to return it to the editor.
It replaces the currently selected artwork entry using the existing image-editing
controls. Other timed entries and pending metadata edits remain intact. Click the
metadata editor's **Apply** to save everything together; **Cancel** discards the
pending changes. Cancelling the search keeps the editor's previous artwork choice.

Search sends the entered terms to the chosen service only when you click Search.
Up to 25 results are shown. No results does not prove that artwork is unavailable:
try different terms, another store region, or the other provider. Network failures,
rate limits, invalid tokens, and unusable images appear in the dialog. iTunes
high-resolution image URLs are best effort and may fall back to the returned image;
Discogs uses each release's returned cover. Search does not update Track tags.
