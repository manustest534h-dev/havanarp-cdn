package com.havanarp.daftarna;

import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteOpenHelper;

import java.util.ArrayList;
import java.util.List;

public final class NotesRepository extends SQLiteOpenHelper {
    private static final String DATABASE_NAME = "daftarna.db";
    private static final int DATABASE_VERSION = 1;
    private static final String TABLE = "notes";

    public NotesRepository(Context context) {
        super(context, DATABASE_NAME, null, DATABASE_VERSION);
    }

    @Override
    public void onCreate(SQLiteDatabase db) {
        db.execSQL("CREATE TABLE " + TABLE + " (" +
                "id INTEGER PRIMARY KEY AUTOINCREMENT," +
                "title TEXT NOT NULL DEFAULT ''," +
                "body TEXT NOT NULL DEFAULT ''," +
                "category TEXT NOT NULL DEFAULT 'عام'," +
                "color INTEGER NOT NULL," +
                "pinned INTEGER NOT NULL DEFAULT 0," +
                "archived INTEGER NOT NULL DEFAULT 0," +
                "created_at INTEGER NOT NULL," +
                "updated_at INTEGER NOT NULL)");
        db.execSQL("CREATE INDEX notes_visible_order ON " + TABLE +
                " (archived, pinned DESC, updated_at DESC)");
    }

    @Override
    public void onUpgrade(SQLiteDatabase db, int oldVersion, int newVersion) {
        // Schema migrations will be added when the database version changes.
    }

    public long save(Note note) {
        long now = System.currentTimeMillis();
        ContentValues values = toValues(note);
        values.put("updated_at", now);
        if (note.id <= 0) {
            values.put("created_at", now);
            note.id = getWritableDatabase().insertOrThrow(TABLE, null, values);
        } else {
            getWritableDatabase().update(TABLE, values, "id = ?",
                    new String[]{String.valueOf(note.id)});
        }
        note.updatedAt = now;
        return note.id;
    }

    public Note get(long id) {
        try (Cursor cursor = getReadableDatabase().query(TABLE, null, "id = ?",
                new String[]{String.valueOf(id)}, null, null, null)) {
            return cursor.moveToFirst() ? fromCursor(cursor) : null;
        }
    }

    public List<Note> list(String query, String filter, boolean archived) {
        List<String> args = new ArrayList<>();
        StringBuilder where = new StringBuilder("archived = ?");
        args.add(archived ? "1" : "0");

        String cleanQuery = NoteUtils.clean(query);
        if (!cleanQuery.isEmpty()) {
            where.append(" AND (title LIKE ? ESCAPE '\\' OR body LIKE ? ESCAPE '\\')");
            String like = "%" + escapeLike(cleanQuery) + "%";
            args.add(like);
            args.add(like);
        }

        if ("المثبتة".equals(filter)) {
            where.append(" AND pinned = 1");
        } else if (filter != null && !"الكل".equals(filter)) {
            where.append(" AND category = ?");
            args.add(filter);
        }

        List<Note> notes = new ArrayList<>();
        try (Cursor cursor = getReadableDatabase().query(TABLE, null, where.toString(),
                args.toArray(new String[0]), null, null, "pinned DESC, updated_at DESC")) {
            while (cursor.moveToNext()) {
                notes.add(fromCursor(cursor));
            }
        }
        return notes;
    }

    public void setPinned(long id, boolean pinned) {
        updateFlag(id, "pinned", pinned);
    }

    public void setArchived(long id, boolean archived) {
        updateFlag(id, "archived", archived);
    }

    public void delete(long id) {
        getWritableDatabase().delete(TABLE, "id = ?", new String[]{String.valueOf(id)});
    }

    private void updateFlag(long id, String field, boolean value) {
        ContentValues values = new ContentValues();
        values.put(field, value ? 1 : 0);
        values.put("updated_at", System.currentTimeMillis());
        getWritableDatabase().update(TABLE, values, "id = ?", new String[]{String.valueOf(id)});
    }

    private static ContentValues toValues(Note note) {
        ContentValues values = new ContentValues();
        values.put("title", NoteUtils.clean(note.title));
        values.put("body", NoteUtils.clean(note.body));
        values.put("category", note.category);
        values.put("color", note.color);
        values.put("pinned", note.pinned ? 1 : 0);
        values.put("archived", note.archived ? 1 : 0);
        return values;
    }

    private static Note fromCursor(Cursor cursor) {
        Note note = new Note();
        note.id = cursor.getLong(cursor.getColumnIndexOrThrow("id"));
        note.title = cursor.getString(cursor.getColumnIndexOrThrow("title"));
        note.body = cursor.getString(cursor.getColumnIndexOrThrow("body"));
        note.category = cursor.getString(cursor.getColumnIndexOrThrow("category"));
        note.color = cursor.getInt(cursor.getColumnIndexOrThrow("color"));
        note.pinned = cursor.getInt(cursor.getColumnIndexOrThrow("pinned")) == 1;
        note.archived = cursor.getInt(cursor.getColumnIndexOrThrow("archived")) == 1;
        note.createdAt = cursor.getLong(cursor.getColumnIndexOrThrow("created_at"));
        note.updatedAt = cursor.getLong(cursor.getColumnIndexOrThrow("updated_at"));
        return note;
    }

    private static String escapeLike(String value) {
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_");
    }
}
