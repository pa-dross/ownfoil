"""An offline library must not lose its files' verification history."""
import datetime
import os
import base64

from db import Files, db, missing_file_count, purge_missing_files, remove_missing_files_from_db
from tasks import handle_file_added_task, handle_file_deleted_task, handle_dir_deleted_task


def test_scan_marks_missing_and_recovery_keeps_verdict(shop_app):
    with shop_app.app.app_context():
        file = Files.query.first()
        file_id, path = file.id, file.filepath
        file.hash_valid = True
        file.signature_valid = True
        file.verified_at = datetime.datetime.utcnow()
        file.mtime = os.path.getmtime(path)
        db.session.commit()

        os.rename(shop_app.library_root, shop_app.library_root + '-offline')
        try:
            remove_missing_files_from_db()
            db.session.expire_all()
            assert missing_file_count() == Files.query.count()
            assert db.session.get(Files, file_id).hash_valid is True
        finally:
            os.rename(shop_app.library_root + '-offline', shop_app.library_root)

        handle_file_added_task(shop_app.library_root, path)
        db.session.expire_all()
        restored = db.session.get(Files, file_id)
        assert restored.missing_since is None
        assert restored.hash_valid is True
        assert restored.verified_at is not None
        assert purge_missing_files() == 0


def test_watcher_events_are_reversible_until_explicit_purge(shop_app):
    with shop_app.app.app_context():
        file = Files.query.first()
        file_id, path = file.id, file.filepath
        file.hash_valid = True
        file.mtime = os.path.getmtime(path)
        db.session.commit()

        os.rename(path, path + '-offline')
        handle_file_deleted_task(path)
        assert db.session.get(Files, file_id).missing_since is not None
        assert db.session.get(Files, file_id).hash_valid is True
        os.rename(path + '-offline', path)
        assert purge_missing_files() == 0  # A recovered file must never be purged.

        handle_file_added_task(shop_app.library_root, path)
        assert db.session.get(Files, file_id).missing_since is None

        handle_dir_deleted_task(os.path.dirname(path))
        assert db.session.get(Files, file_id).missing_since is not None
        os.remove(path)
        assert purge_missing_files() >= 1
        assert db.session.get(Files, file_id) is None


def test_files_api_exposes_missing_state_and_invalidates_etag(shop_app):
    with shop_app.app.app_context():
        file = Files.query.first()
        file_id, path = file.id, file.filepath
    query = '{ file(id: "%s") { missingSince verifiedAt } }' % file_id
    url = '/api/graphql'
    credentials = base64.b64encode(b'admin:adminpass1').decode()
    headers = {'Authorization': 'Basic ' + credentials}
    first = shop_app.client.get(url, query_string={'query': query}, headers=headers)
    assert first.status_code == 200
    assert first.json['data']['file']['missingSince'] is None
    with shop_app.app.app_context():
        os.rename(path, path + '-offline')
        try:
            remove_missing_files_from_db()
            second = shop_app.client.get(url, query_string={'query': query},
                                         headers={**headers, 'If-None-Match': first.headers['ETag']})
            assert second.status_code == 200
            assert second.json['data']['file']['missingSince'] is not None
        finally:
            os.rename(path + '-offline', path)
