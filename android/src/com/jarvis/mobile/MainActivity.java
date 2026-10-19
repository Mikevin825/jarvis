package com.jarvis.mobile;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.AlertDialog;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import android.text.InputType;
import android.view.Menu;
import android.view.MenuItem;
import android.view.View;
import android.webkit.PermissionRequest;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.app.Activity;
import android.graphics.Color;
import android.view.Gravity;

/**
 * A thin native shell around the JARVIS web app.
 *
 * Deliberately thin: all the conversation logic lives on the server and in the
 * PWA. This activity exists to give the app a real launcher icon, a persistent
 * WebView (so localStorage keeps the pairing token), microphone access, and a
 * native "cannot reach the server" screen instead of a browser error page.
 */
public class MainActivity extends Activity {

    private static final String PREFS = "jarvis";
    private static final String KEY_URL = "server_url";
    private static final String DEFAULT_URL = "http://192.168.1.33:8794/";

    private WebView web;
    private FrameLayout root;
    private ProgressBar spinner;
    private TextView errorView;
    private String serverUrl;

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        SharedPreferences prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        serverUrl = prefs.getString(KEY_URL, DEFAULT_URL);

        root = new FrameLayout(this);
        root.setBackgroundColor(Color.parseColor("#0a0a12"));

        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);          // localStorage — the pairing token
        s.setDatabaseEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(true);
        s.setCacheMode(WebSettings.LOAD_NO_CACHE); // the API must never be stale

        web.setBackgroundColor(Color.parseColor("#0a0a12"));

        // Microphone: the web app calls getUserMedia / SpeechRecognition, which
        // arrives here as a PermissionRequest. Grant only audio.
        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onPermissionRequest(final PermissionRequest request) {
                runOnUiThread(() -> {
                    for (String r : request.getResources()) {
                        if (PermissionRequest.RESOURCE_AUDIO_CAPTURE.equals(r)) {
                            request.grant(new String[]{r});
                            return;
                        }
                    }
                    request.deny();
                });
            }
        });

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest req) {
                // Keep every navigation inside the app.
                return false;
            }

            @Override
            public void onPageFinished(WebView v, String url) {
                spinner.setVisibility(View.GONE);
                errorView.setVisibility(View.GONE);
                web.setVisibility(View.VISIBLE);
            }

            @Override
            public void onReceivedError(WebView v, WebResourceRequest req,
                                        WebResourceError err) {
                // Only the main document failing means the server is down.
                if (req.isForMainFrame()) showUnreachable();
            }
        });

        spinner = new ProgressBar(this);
        spinner.setVisibility(View.VISIBLE);
        FrameLayout.LayoutParams spinParams = new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.WRAP_CONTENT,
                FrameLayout.LayoutParams.WRAP_CONTENT);
        spinParams.gravity = Gravity.CENTER;
        spinner.setLayoutParams(spinParams);

        errorView = buildErrorView();

        root.addView(web);
        root.addView(spinner);
        root.addView(errorView);
        setContentView(root);

        askMicPermission();
        web.loadUrl(serverUrl);
    }

    /** The native fallback shown when the server cannot be reached. */
    private TextView buildErrorView() {
        TextView tv = new TextView(this);
        tv.setTextColor(Color.parseColor("#8b8b9a"));
        tv.setTextSize(15);
        tv.setGravity(Gravity.CENTER);
        tv.setPadding(48, 48, 48, 48);
        tv.setVisibility(View.GONE);
        tv.setOnClickListener(v -> showUrlDialog());
        tv.setText("Cannot reach JARVIS.\n\n"
                + "Make sure the server is running on your computer\n"
                + "(./jarvis-mobile) and that this phone is on\n"
                + "the same wifi.\n\n"
                + "Tap here to change the server address.\n\n"
                + serverUrl);
        return tv;
    }

    private void showUnreachable() {
        spinner.setVisibility(View.GONE);
        web.setVisibility(View.GONE);
        errorView.setText("Cannot reach JARVIS.\n\n"
                + "Make sure the server is running on your computer\n"
                + "(./jarvis-mobile) and that this phone is on\n"
                + "the same wifi.\n\n"
                + "Tap here to change the server address.\n\n"
                + serverUrl);
        errorView.setVisibility(View.VISIBLE);
    }

    private void askMicPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            if (checkSelfPermission(Manifest.permission.RECORD_AUDIO)
                    != PackageManager.PERMISSION_GRANTED) {
                requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, 7);
            }
        }
    }

    /** A dialog to set the server address, so the app is not hard-coded to one IP. */
    private void showUrlDialog() {
        final EditText input = new EditText(this);
        input.setInputType(InputType.TYPE_TEXT_VARIATION_URI);
        input.setText(serverUrl);
        input.setSelectAllOnFocus(true);

        LinearLayout wrap = new LinearLayout(this);
        wrap.setPadding(48, 24, 48, 0);
        wrap.addView(input);

        new AlertDialog.Builder(this)
                .setTitle("JARVIS server address")
                .setMessage("The URL printed by ./jarvis-mobile")
                .setView(wrap)
                .setPositiveButton("Save", (d, w) -> {
                    String url = input.getText().toString().trim();
                    if (!url.startsWith("http")) url = "http://" + url;
                    if (!url.endsWith("/")) url = url + "/";
                    serverUrl = url;
                    getSharedPreferences(PREFS, MODE_PRIVATE)
                            .edit().putString(KEY_URL, url).apply();
                    web.setVisibility(View.VISIBLE);
                    spinner.setVisibility(View.VISIBLE);
                    errorView.setVisibility(View.GONE);
                    web.loadUrl(serverUrl);
                })
                .setNegativeButton("Cancel", null)
                .show();
    }

    @Override
    public boolean onCreateOptionsMenu(Menu menu) {
        menu.add(0, 1, 0, "Server address");
        menu.add(0, 2, 1, "Reload");
        return true;
    }

    @Override
    public boolean onOptionsItemSelected(MenuItem item) {
        if (item.getItemId() == 1) {
            showUrlDialog();
            return true;
        }
        if (item.getItemId() == 2) {
            web.reload();
            return true;
        }
        return super.onOptionsItemSelected(item);
    }

    @Override
    public void onBackPressed() {
        if (web.canGoBack()) {
            web.goBack();
        } else {
            super.onBackPressed();
        }
    }
}
