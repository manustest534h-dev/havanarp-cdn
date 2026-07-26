package com.havanarp.daftarna;

import android.app.Activity;
import android.app.AlertDialog;
import android.os.Bundle;
import android.view.View;
import android.widget.ArrayAdapter;
import android.widget.EditText;
import android.widget.RadioGroup;
import android.widget.Spinner;
import android.widget.Switch;
import android.widget.TextView;
import android.widget.Toast;

import java.util.Arrays;
import java.util.List;

public final class EditorActivity extends Activity {
    public static final String EXTRA_NOTE_ID = "note_id";
    private static final List<String> CATEGORIES = Arrays.asList(
            "عام", "الشغل", "البيت", "الدراسة", "شخصي");

    private NotesRepository repository;
    private Note note;
    private EditText titleInput;
    private EditText bodyInput;
    private Spinner categorySpinner;
    private RadioGroup colorGroup;
    private Switch pinnedSwitch;
    private String originalSignature;
    private boolean saved;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_editor);
        getWindow().getDecorView().setLayoutDirection(View.LAYOUT_DIRECTION_RTL);

        repository = new NotesRepository(this);
        titleInput = findViewById(R.id.titleInput);
        bodyInput = findViewById(R.id.bodyInput);
        categorySpinner = findViewById(R.id.categorySpinner);
        colorGroup = findViewById(R.id.colorGroup);
        pinnedSwitch = findViewById(R.id.pinnedSwitch);

        ArrayAdapter<String> categories = new ArrayAdapter<>(this,
                android.R.layout.simple_spinner_item, CATEGORIES);
        categories.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        categorySpinner.setAdapter(categories);

        long noteId = getIntent().getLongExtra(EXTRA_NOTE_ID, -1);
        note = noteId > 0 ? repository.get(noteId) : new Note();
        if (note == null) {
            Toast.makeText(this, "الملاحظة مش موجودة", Toast.LENGTH_SHORT).show();
            finish();
            return;
        }

        boolean editing = note.id > 0;
        ((TextView) findViewById(R.id.editorHeading)).setText(
                editing ? "عدّل الملاحظة" : "ملاحظة جديدة");
        View deleteButton = findViewById(R.id.deleteButton);
        deleteButton.setVisibility(editing ? View.VISIBLE : View.INVISIBLE);
        deleteButton.setOnClickListener(view -> confirmDelete());
        findViewById(R.id.backButton).setOnClickListener(view -> attemptClose());
        findViewById(R.id.saveButton).setOnClickListener(view -> saveAndClose());

        populateFields();
        originalSignature = signature();
    }

    @Override
    @SuppressWarnings("deprecation")
    public void onBackPressed() {
        attemptClose();
    }

    @Override
    protected void onDestroy() {
        repository.close();
        super.onDestroy();
    }

    private void populateFields() {
        titleInput.setText(note.title);
        bodyInput.setText(note.body);
        int categoryIndex = CATEGORIES.indexOf(note.category);
        categorySpinner.setSelection(Math.max(0, categoryIndex));
        pinnedSwitch.setChecked(note.pinned);
        if (note.color == 0xFF1B7F79) {
            colorGroup.check(R.id.colorGreen);
        } else if (note.color == 0xFF5577C6) {
            colorGroup.check(R.id.colorBlue);
        } else if (note.color == 0xFFC85A7C) {
            colorGroup.check(R.id.colorRose);
        } else {
            colorGroup.check(R.id.colorAmber);
        }
        titleInput.setSelection(titleInput.length());
    }

    private void saveAndClose() {
        String title = NoteUtils.clean(titleInput.getText().toString());
        String body = NoteUtils.clean(bodyInput.getText().toString());
        if (title.isEmpty() && body.isEmpty()) {
            titleInput.setError("اكتب عنوان أو تفاصيل للملاحظة");
            titleInput.requestFocus();
            return;
        }

        note.title = title;
        note.body = body;
        note.category = categorySpinner.getSelectedItem().toString();
        note.pinned = pinnedSwitch.isChecked();
        note.color = selectedColor();
        repository.save(note);
        saved = true;
        Toast.makeText(this, "انحفظت، تمام!", Toast.LENGTH_SHORT).show();
        finish();
    }

    private void attemptClose() {
        if (saved || signature().equals(originalSignature)) {
            finish();
            return;
        }
        new AlertDialog.Builder(this)
                .setTitle("تطلع بدون حفظ؟")
                .setMessage("في تغييرات لسه ما حفظتها.")
                .setNegativeButton("كمّل كتابة", null)
                .setPositiveButton("اطلع", (dialog, which) -> finish())
                .show();
    }

    private void confirmDelete() {
        new AlertDialog.Builder(this)
                .setTitle("متأكد بدّك تحذفها؟")
                .setMessage("الحذف نهائي وما بنقدر نرجّع الملاحظة بعده.")
                .setNegativeButton("لا، خلّيها", null)
                .setPositiveButton("احذف", (dialog, which) -> {
                    repository.delete(note.id);
                    saved = true;
                    Toast.makeText(this, "انحذفت الملاحظة", Toast.LENGTH_SHORT).show();
                    finish();
                })
                .show();
    }

    private int selectedColor() {
        int checked = colorGroup.getCheckedRadioButtonId();
        if (checked == R.id.colorGreen) return 0xFF1B7F79;
        if (checked == R.id.colorBlue) return 0xFF5577C6;
        if (checked == R.id.colorRose) return 0xFFC85A7C;
        return 0xFFF6A03D;
    }

    private String signature() {
        Object category = categorySpinner.getSelectedItem();
        return titleInput.getText() + "\u0001" + bodyInput.getText() + "\u0001" +
                (category == null ? "" : category.toString()) + "\u0001" +
                pinnedSwitch.isChecked() + "\u0001" + selectedColor();
    }
}
