package com.havanarp.daftarna;

public final class Note {
    public long id;
    public String title;
    public String body;
    public String category;
    public int color;
    public boolean pinned;
    public boolean archived;
    public long createdAt;
    public long updatedAt;

    public Note() {
        title = "";
        body = "";
        category = "عام";
        color = 0xFFF6A03D;
    }
}
