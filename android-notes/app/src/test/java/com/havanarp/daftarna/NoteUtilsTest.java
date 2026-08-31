package com.havanarp.daftarna;

import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

public class NoteUtilsTest {
    @Test
    public void usesBodyAsTitleWhenTitleIsEmpty() {
        assertEquals("اشتري خبز وحليب", NoteUtils.displayTitle("", "  اشتري خبز وحليب  "));
    }

    @Test
    public void givesEmptyNoteAFriendlyTitle() {
        assertEquals("ملاحظة بدون عنوان", NoteUtils.displayTitle(" ", "\n"));
    }

    @Test
    public void normalizesPreviewWhitespace() {
        assertEquals("سطر أول سطر ثاني", NoteUtils.preview("سطر أول\n   سطر ثاني"));
    }

    @Test
    public void truncatesLongFallbackTitle() {
        String title = NoteUtils.displayTitle("", "هذه ملاحظة طويلة جداً ومقصود منها التأكد من اختصار العنوان بشكل لطيف");
        assertTrue(title.endsWith("…"));
        assertTrue(title.length() <= 37);
    }
}
