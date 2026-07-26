package com.havanarp.daftarna;

import android.content.Context;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.BaseAdapter;
import android.widget.TextView;

import java.util.ArrayList;
import java.util.List;

public final class NoteAdapter extends BaseAdapter {
    private final LayoutInflater inflater;
    private List<Note> notes = new ArrayList<>();

    public NoteAdapter(Context context) {
        inflater = LayoutInflater.from(context);
    }

    public void submit(List<Note> values) {
        notes = values;
        notifyDataSetChanged();
    }

    @Override public int getCount() { return notes.size(); }
    @Override public Note getItem(int position) { return notes.get(position); }
    @Override public long getItemId(int position) { return notes.get(position).id; }

    @Override
    public View getView(int position, View convertView, ViewGroup parent) {
        ViewHolder holder;
        if (convertView == null) {
            convertView = inflater.inflate(R.layout.item_note, parent, false);
            holder = new ViewHolder(convertView);
            convertView.setTag(holder);
        } else {
            holder = (ViewHolder) convertView.getTag();
        }

        Note note = getItem(position);
        holder.title.setText(NoteUtils.displayTitle(note.title, note.body));
        String preview = NoteUtils.preview(note.body);
        holder.body.setText(preview);
        holder.body.setVisibility(preview.isEmpty() ? View.GONE : View.VISIBLE);
        holder.category.setText(note.category);
        holder.time.setText(NoteUtils.formatModified(note.updatedAt));
        holder.pin.setVisibility(note.pinned ? View.VISIBLE : View.GONE);
        holder.colorBar.setBackgroundColor(note.color);

        GradientDrawable background = new GradientDrawable();
        background.setColor(Color.WHITE);
        background.setCornerRadius(dp(parent.getContext(), 16));
        background.setStroke(dp(parent.getContext(), 1), 0xFFE7E9E4);
        holder.container.setBackground(background);
        holder.container.setElevation(dp(parent.getContext(), 1));
        return convertView;
    }

    private static int dp(Context context, int value) {
        return Math.round(value * context.getResources().getDisplayMetrics().density);
    }

    private static final class ViewHolder {
        final View container;
        final View colorBar;
        final TextView title;
        final TextView body;
        final TextView category;
        final TextView time;
        final TextView pin;

        ViewHolder(View view) {
            container = view.findViewById(R.id.rowContainer);
            colorBar = view.findViewById(R.id.colorBar);
            title = view.findViewById(R.id.noteTitle);
            body = view.findViewById(R.id.noteBody);
            category = view.findViewById(R.id.noteCategory);
            time = view.findViewById(R.id.noteTime);
            pin = view.findViewById(R.id.pinIcon);
        }
    }
}
