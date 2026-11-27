# Phone Desk

Phone Desk captures a trusted USB-connected iPhone display through CoreMediaIO and AVFoundation. Browser gestures and agent actions use pymobiledevice3 Universal HID on the selected phone. To open an app, the agent finds its icon or a search result, taps it, and checks the next frame.

## Start

Connect and unlock the phone, trust the Mac, and enable Developer Mode. Run `./start.command` and visit http://127.0.0.1:8766. Allow Camera access for the launching Mac process when prompted. The capture helper reads verified device associations from build/capture-bindings.json. Start a paired pymobiledevice3 tunneld session for the selected phone before clicking. Phone Desk sends touch reports through that tunnel. Verify each gesture on the live preview.

The launcher needs Swift and Python with the packages in requirements.txt. For a physical phone, give instructions in the active Codex chat and use browser control on the live dashboard. The local server streams the preview to the browser. Browser clicks and drags use the selected phone’s USB input connection. The sandbox has its own local demo agent.

Run the checks with `python3 -m unittest discover -v -s tests`.

Keep the launcher open. It automatically reloads changes to the Python server, agent instructions, and Swift capture helper. A reload ends active agent tasks. Refresh the browser to pick up dashboard UI changes.
