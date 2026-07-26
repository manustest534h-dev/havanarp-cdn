package com.havanarp.daftarna;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.view.Menu;
import android.view.MenuItem;
import android.view.View;
import android.widget.LinearLayout;
import android.widget.ListView;
import android.widget.PopupMenu;
import android.widget.SearchView;
import android.widget.TextView;
import android.widget.Toast;

import java.util.List;

public final class MainActivity extends Activity {
    private static final String[] FILTERS = {"الكل", "المثبتة", "الشغل", "البيت", "الدراسة", "شخصي"};
    private static final int MENU_NOTES = 10;
    private static final int MENU_ARCHIVE = 11;
    private static final int MENU_SHARE_ALL = 12;
    private static final int MENU_ABOUT = 13;

    private NotesRepository repository;
    private NoteAdapter adapter;
    private LinearLayout filterRow;
    private View emptyState;
    private TextView emptyTitle;
    private TextView emptyBody;
    private TextView screenTitle;
    private TextView screenSubtitle;
    private String selectedFilter = "الكل";
    private String query = "";
    private boolean archiveMode;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);
        getWindow().getDecorView().setLayoutDirection(View.LAYOUT_DIRECTION_RTL);

        repository = new NotesRepository(this);
        adapter = new NoteAdapter(this);
        filterRow = findViewById(R.id.filterRow);
        emptyState = findViewById(R.id.emptyState);
        emptyTitle = findViewById(R.id.emptyTitle);
        emptyBody = findViewById(R.id.emptyBody);
        screenTitle = findViewById(R.id.screenTitle);
        screenSubtitle = findViewById(R.id.screenSubtitle);

        ListView notesList = findViewById(R.id.notesList);
        notesList.setAdapter(adapter);
        notesList.setOnItemClickListener((parent, view, position, id) -> openEditor(id));
        notesList.setOnItemLongClickListener((parent, view, position, id) -> {
            showNoteActions(view, adapter.getItem(position));
            return true;
        });

        SearchView searchView = findViewById(R.id.searchView);
        searchView.setOnQueryTextListener(new SearchView.OnQueryTextListener() {
            @Override public boolean onQueryTextSubmit(String text) { return true; }

            @Override
            public boolean onQueryTextChange(String text) {
                query = text;
                reload();
                return true;
            }
        });

        findViewById(R.id.addButton).setOnClickListener(view -> openEditor(-1));
        findViewById(R.id.moreButton).setOnClickListener(this::showMainMenu);
        renderFilters();
    }

    @Override
    protected void onResume() {
        super.onResume();
        reload();
    }

    @Override
    protected void onDestroy() {
        repository.close();
        super.onDestroy();
    }

    private void reload() {
        List<Note> notes = repository.list(query, selectedFilter, archiveMode);
        adapter.submit(notes);
        boolean empty = notes.isEmpty();
        emptyState.setVisibility(empty ? View.VISIBLE : View.GONE);
        if (archiveMode) {
            screenTitle.setText("الأرشيف");
            screenSubtitle.setText("ملاحظاتك القديمة محفوظة هون");
            emptyTitle.setText("الأرشيف فاضي");
            emptyBody.setText("لما تأرشف ملاحظة بتلاقيها هون وبتقدر ترجعها بأي وقت.");
        } else if (!NoteUtils.clean(query).isEmpty()) {
            emptyTitle.setText("ما لقينا نتيجة");
            emptyBody.setText("جرّب كلمة ثانية أو اختار تصنيف مختلف.");
        } else {
            screenTitle.setText("دفترنا");
            screenSubtitle.setText("كل اللي ببالك، بمكان واحد");
            emptyTitle.setText("لسّه ما كتبت إشي هون");
            emptyBody.setText("اكبس على زر + ودوّنها قبل ما تطير من بالك.");
        }
    }

    private void renderFilters() {
        filterRow.removeAllViews();
        for (String filter : FILTERS) {
            TextView chip = new TextView(this);
            chip.setText(filter);
            chip.setTextSize(14);
            chip.setGravity(View.TEXT_ALIGNMENT_CENTER);
            chip.setGravity(android.view.Gravity.CENTER);
            chip.setPadding(dp(16), 0, dp(16), 0);
            LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.WRAP_CONTENT, dp(42));
            params.setMarginEnd(dp(8));
            chip.setLayoutParams(params);
            styleChip(chip, filter.equals(selectedFilter));
            chip.setOnClickListener(view -> {
                selectedFilter = filter;
                renderFilters();
                reload();
            });
            filterRow.addView(chip);
        }
    }

    private void styleChip(TextView chip, boolean selected) {
        GradientDrawable shape = new GradientDrawable();
        shape.setCornerRadius(dp(20));
        shape.setColor(selected ? 0xFF1B7F79 : Color.WHITE);
        shape.setStroke(dp(1), selected ? 0xFF1B7F79 : 0xFFE1E5DF);
        chip.setTextColor(selected ? Color.WHITE : 0xFF475467);
        chip.setBackground(shape);
    }

    private void openEditor(long noteId) {
        Intent intent = new Intent(this, EditorActivity.class);
        if (noteId > 0) {
            intent.putExtra(EditorActivity.EXTRA_NOTE_ID, noteId);
        }
        startActivity(intent);
    }

    private void showMainMenu(View anchor) {
        PopupMenu popup = new PopupMenu(this, anchor);
        Menu menu = popup.getMenu();
        menu.add(Menu.NONE, archiveMode ? MENU_NOTES : MENU_ARCHIVE, 0,
                archiveMode ? "ارجع للملاحظات" : "افتح الأرشيف");
        menu.add(Menu.NONE, MENU_SHARE_ALL, 1, "شارك كل الملاحظات");
        menu.add(Menu.NONE, MENU_ABOUT, 2, "عن دفترنا");
        popup.setOnMenuItemClickListener(this::handleMainMenu);
        popup.show();
    }

    private boolean handleMainMenu(MenuItem item) {
        if (item.getItemId() == MENU_NOTES || item.getItemId() == MENU_ARCHIVE) {
            archiveMode = item.getItemId() == MENU_ARCHIVE;
            selectedFilter = "الكل";
            query = "";
            ((SearchView) findViewById(R.id.searchView)).setQuery("", false);
            renderFilters();
            reload();
            return true;
        }
        if (item.getItemId() == MENU_SHARE_ALL) {
            shareAll();
            return true;
        }
        if (item.getItemId() == MENU_ABOUT) {
            new AlertDialog.Builder(this)
                    .setTitle("دفترنا")
                    .setMessage("دفتر ملاحظات عربي بسيط وسريع. ملاحظاتك بتضل محفوظة على جهازك وبتشتغل بدون إنترنت.\n\nالإصدار 1.0.0")
                    .setPositiveButton("تمام", null)
                    .show();
            return true;
        }
        return false;
    }

    private void showNoteActions(View anchor, Note note) {
        PopupMenu popup = new PopupMenu(this, anchor);
        Menu menu = popup.getMenu();
        menu.add(note.pinned ? "شيل التثبيت" : "ثبّت فوق");
        menu.add(note.archived ? "رجّع للملاحظات" : "حط بالأرشيف");
        menu.add("شارك");
        menu.add("احذف");
        popup.setOnMenuItemClickListener(item -> {
            String action = item.getTitle().toString();
            if (action.contains("تثبيت") || action.contains("ثبّت")) {
                repository.setPinned(note.id, !note.pinned);
                toast(note.pinned ? "انشال التثبيت" : "تم التثبيت فوق");
                reload();
            } else if (action.contains("الأرشيف") || action.contains("رجّع")) {
                repository.setArchived(note.id, !note.archived);
                toast(note.archived ? "رجعت الملاحظة" : "انحفظت بالأرشيف");
                reload();
            } else if (action.equals("شارك")) {
                share(note);
            } else if (action.equals("احذف")) {
                confirmDelete(note);
            }
            return true;
        });
        popup.show();
    }

    private void confirmDelete(Note note) {
        new AlertDialog.Builder(this)
                .setTitle("متأكد بدّك تحذفها؟")
                .setMessage("الحذف نهائي وما بنقدر نرجّع الملاحظة بعده.")
                .setNegativeButton("لا، خلّيها", null)
                .setPositiveButton("احذف", (dialog, which) -> {
                    repository.delete(note.id);
                    toast("انحذفت الملاحظة");
                    reload();
                })
                .show();
    }

    private void share(Note note) {
        String text = NoteUtils.displayTitle(note.title, note.body) + "\n\n" + NoteUtils.clean(note.body);
        shareText(text);
    }

    private void shareAll() {
        List<Note> notes = repository.list("", "الكل", archiveMode);
        if (notes.isEmpty()) {
            toast("ما في ملاحظات عشان نشاركها");
            return;
        }
        StringBuilder text = new StringBuilder("ملاحظاتي من دفترنا\n\n");
        for (Note note : notes) {
            text.append("• ").append(NoteUtils.displayTitle(note.title, note.body)).append('\n');
            if (!NoteUtils.clean(note.body).isEmpty()) {
                text.append(NoteUtils.clean(note.body)).append('\n');
            }
            text.append('\n');
        }
        shareText(text.toString().trim());
    }

    private void shareText(String text) {
        Intent intent = new Intent(Intent.ACTION_SEND);
        intent.setType("text/plain");
        intent.putExtra(Intent.EXTRA_TEXT, text);
        startActivity(Intent.createChooser(intent, "شارك عن طريق"));
    }

    private void toast(String message) {
        Toast.makeText(this, message, Toast.LENGTH_SHORT).show();
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }
}
