from aiohttp import web
import json
from os import path
import os
import shutil
from datetime import datetime, timezone

from ..utils import get_target_folder_files, get_parent_path, get_info_filename, \
    image_extensions, video_extensions

# folder_path, folder_type
async def api_get_files(request):
    folder_path = request.query.get('folder_path', '')
    folder_type = request.query.get('folder_type', 'outputs')

    # New query params:
    # sort_by: 'name' (default) or 'mtime'
    # order: 'asc' (default) or 'desc'
    sort_by = request.query.get('sort_by', 'name')
    order = request.query.get('order', 'asc')
    sort_by = sort_by if sort_by in ('name', 'mtime') else 'name'
    order = order if order in ('asc', 'desc') else 'asc'
    reverse = order == 'desc'

    files = get_target_folder_files(folder_path, folder_type=folder_type)

    if files == None:
        return web.Response(status=404)

    # If client requested mtime sorting (or if you want to always return mtime),
    # enrich file entries with 'mtime' (ISO 8601 UTC) so client can display it.
    if sort_by == 'mtime':
        parent_path = get_parent_path(folder_type)
        for f in files:
            try:
                fp = path.join(parent_path, folder_path, f.get('name', ''))
                if path.exists(fp):
                    mtime_ts = os.path.getmtime(fp)
                    f['mtime'] = datetime.fromtimestamp(mtime_ts, tz=timezone.utc).isoformat()
                else:
                    # file doesn't exist on disk (maybe removed) -> set to epoch
                    f['mtime'] = datetime.fromtimestamp(0, tz=timezone.utc).isoformat()
            except Exception:
                # On error, fall back to epoch
                f['mtime'] = datetime.fromtimestamp(0, tz=timezone.utc).isoformat()

    # Sorting logic:
    if sort_by == 'name':
        # keep directories before files, then case-insensitive name sort
        files.sort(key=lambda e: (not e.get('is_dir', False), e.get('name', '').lower()), reverse=reverse)
    else:  # sort_by == 'mtime'
        def _mtime_key(e):
            v = e.get('mtime')
            if not v:
                # missing mtime => treat as very old
                return datetime.fromtimestamp(0, tz=timezone.utc)
            try:
                return datetime.fromisoformat(v)
            except Exception:
                return datetime.fromtimestamp(0, tz=timezone.utc)
        # If you prefer directories-first for mtime as well, you can return a tuple:
        # files.sort(key=lambda e: (not e.get('is_dir', False), _mtime_key(e)), reverse=reverse)
        files.sort(key=_mtime_key, reverse=reverse)

    return web.json_response({
        'files': files
    })


# filename, folder_path, folder_type
async def api_delete_file(request):
    json_data = await request.json()
    filename = json_data['filename']
    folder_path = json_data.get('folder_path', '')
    folder_type = json_data.get('folder_type', 'outputs')

    parent_path = get_parent_path(folder_type)
    target_path = path.join(parent_path, folder_path, filename)
    if not path.exists(target_path):
        return web.json_response(status=404)

    if path.isdir(target_path):
        shutil.rmtree(target_path)
    else:
        os.remove(target_path)
    info_file_path = get_info_filename(target_path)
    if path.exists(info_file_path):
        os.remove(info_file_path)

    return web.Response(status=201)


# filename, folder_path, folder_type, new_data: {}
async def api_update_file(request):
    json_data = await request.json()
    filename = json_data['filename']
    folder_path = json_data.get('folder_path', '')
    folder_type = json_data.get('folder_type', 'outputs')
    parent_path = get_parent_path(folder_type)

    new_data = json_data.get('new_data', None)
    if not new_data:
        return web.Response(status=400)

    new_filename = new_data['filename']
    notes = new_data['notes']

    old_file_path = path.join(parent_path, folder_path, filename)
    new_file_path = path.join(parent_path, folder_path, new_filename)

    if not path.exists(old_file_path):
        return web.Response(status=404)

    if new_filename and filename != new_filename:
        shutil.move(
            old_file_path,
            new_file_path
        )
        old_info_file_path = get_info_filename(old_file_path)
        if path.exists(old_info_file_path):
            new_info_file_path = get_info_filename(new_file_path)
            shutil.move(
                old_info_file_path,
                new_info_file_path
            )

    if notes:
        extra = {
            "notes": notes
        }
        info_file_path = get_info_filename(new_file_path)
        with open(info_file_path, "w", encoding="utf-8") as outfile:
            json.dump(extra, outfile)

    return web.Response(status=201)


# filename, folder_path, folder_type
async def api_view_file(request):
    folder_type = request.query.get("folder_type", "outputs")
    folder_path = request.query.get("folder_path", "")
    filename = request.query.get("filename", None)
    if not filename:
        return web.Response(status=404)

    parent_path = get_parent_path(folder_type)
    file_path = path.join(parent_path, folder_path, filename)

    if not path.exists(file_path):
        return web.Response(status=404)

    with open(file_path, 'rb') as f:
        media_file = f.read()

    content_type = 'application/json'
    file_extension = path.splitext(filename)[1].lower()
    if file_extension in image_extensions:
        content_type = f'image/{file_extension[1:]}'
    if file_extension in video_extensions:
        content_type = f'video/{file_extension[1:]}'

    return web.Response(
        body=media_file,
        content_type=content_type,
        headers={"Content-Disposition": f"filename=\"{filename}\""}
    )
