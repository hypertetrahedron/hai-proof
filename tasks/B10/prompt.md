Uploaded files are occasionally corrupted: they arrive exactly one byte short.

Our app accepts large files from the browser in chunks of a few MB. Each chunk is POSTed as `multipart/form-data` with a single file field and read on the server through `request.files[...]`. For most files every chunk arrives intact. For some files, one chunk is consistently one byte shorter than what the browser sent, and it is always the same chunk of the same file. Re-uploading the same file reproduces it exactly, and changing the chunk size moves the problem to a different chunk or makes it go away.

What we've ruled out, after most of a day:

- The browser and network: the `Content-Length` is right, and a packet capture shows the full chunk arriving.
- Our chunking code: if we POST the same chunk as a raw `application/octet-stream` body and read `request.get_data()`, all bytes are there. Only the multipart route loses one.
- File size alone: large and small files are both affected, and most large files are fine.

It started when we upgraded to the current Werkzeug release, and pinning the previous release makes it go away. We can't attach customer files. One affected chunk is mostly binary zeros, if that helps.

Please find the cause and fix it in Werkzeug, with a regression test. Keep the existing tests passing.
