# Oracle execution host bootstrap

This is a deployment checklist, not a promise that Oracle Always Free capacity is available.

1. Create an Oracle Cloud VM in an eligible region; verify the current free-tier offer and capacity in your account.
2. Prefer an x86_64 VM for the first MT5/Wine compatibility test. ARM compatibility is not assumed.
3. Restrict SSH to your IP, update OS packages, create a non-root service user, configure firewall and disk monitoring.
4. Install Wine and a supported MT5 terminal build according to current vendor terms.
5. Log in to an Exness demo account manually once.
6. Install the EA into that terminal's MQL5 Experts directory and compile in MetaEditor.
7. In MT5 WebRequest settings, allow only your HTTPS API host.
8. Run the Python agent using a virtual environment and systemd.
9. Keep each account's terminal data directory and credentials separate.
10. Verify restart, reconnection and position reconciliation with demo trades.

Do not expose terminal RDP/VNC or agent control ports publicly. Do not place credentials in GitHub.
