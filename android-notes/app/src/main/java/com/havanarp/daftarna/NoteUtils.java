package com.havanarp.daftarna;

import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

public final class NoteUtils {
    private static final Locale JORDAN = new Locale("ar", "JO");

    private NoteUtils() {}

    public static String displayTitle(String title, String body) {
        String cleanTitle = clean(title);
        if (!cleanTitle.isEmpty()) {
            return cleanTitle;
        }
        String cleanBody = clean(body);
        if (cleanBody.isEmpty()) {
            return "ملاحظة بدون عنوان";
        }
        int end = Math.min(cleanBody.length(), 36);
        return cleanBody.substring(0, end) + (cleanBody.length() > end ? "…" : "");
    }

    public static String preview(String body) {
        String value = clean(body).replace('\n', ' ');
        return value.replaceAll("\\s+", " ");
    }

    public static String formatModified(long timestamp) {
        long elapsed = Math.max(0, System.currentTimeMillis() - timestamp);
        if (elapsed < 60_000) {
            return "هسّه";
        }
        if (elapsed < 3_600_000) {
            return "قبل " + (elapsed / 60_000) + " د";
        }
        if (elapsed < 86_400_000) {
            return "قبل " + (elapsed / 3_600_000) + " س";
        }
        return new SimpleDateFormat("d MMM، h:mm a", JORDAN).format(new Date(timestamp));
    }

    public static String clean(String text) {
        return text == null ? "" : text.trim();
    }
}
