📖 What is HyperMove?

HyperMove is a professional-grade graphical utility designed specifically for copying and moving massive amounts of data (like 150GB+ games, raw video files, and massive backups) at the absolute physical limit of your SSDs and HDDs.

By utilizing advanced Direct I/O caching bypass and Hardware Syncing, HyperMove achieves transfer speeds that standard operating system copy windows simply cannot match, all while wrapped in a breathtaking, hardware-accelerated fluid UI.

✨ Key Features

🚀 Direct I/O Engine: Bypasses the standard OS RAM cache to stream data directly from disk to disk, preventing system freezes during massive transfers.

🛡️ Bulletproof Power-Cut Recovery: Features hardware fsync flushing. If your PC loses power at 90GB of a 150GB transfer, HyperMove will safely auto-resume byte-for-byte when you turn it back on.

🌊 Liquid Telemetry Dashboard: Monitor your transfer with a stunning 60FPS fluid dual-wave speed graph that reacts to disk performance in real-time.

🗂️ True Move (Copy + Verify + Delete): Safely moves files by ensuring 100% data integrity before automatically wiping the source files to free up space.

🎨 Native OS Glass UI: Features authentic background blur (Acrylic/Mica on Windows), smooth crossfading drop zones, and premium typography.

📥 How to Download & Install

You don't need to install any code to run this. Simply download the standalone application!

Go to the Releases page of this repository.

Download the latest HyperMove.exe file for Windows.

Double-click the .exe to launch the application instantly. No installation required!

🖥️ How to Use

Launch the App: Open HyperMove.exe.

Select Source: Drag and drop your massive game folder or video files into the top Source drop zone, or click "Folder" to browse.

Select Destination: Drag and drop your target NVMe/HDD into the bottom Destination drop zone.

Choose Operation: Select either Copy (keeps original files) or Move (deletes original files after a safe transfer).

Start: Click START, sit back, and watch the Liquid Telemetry Graph max out your drive speeds.

🛠️ For Developers (Build from Source)

If you want to run the raw Python code or compile the .exe yourself:

# 1. Clone the repository
git clone [https://github.com/yourusername/HyperMove.git](https://github.com/yourusername/HyperMove.git)

# 2. Navigate to the directory
cd HyperMove

# 3. Install required dependencies
pip install PySide6 pyinstaller

# 4. Run the application directly
python main.py

# 5. Build the standalone executable
pyinstaller --noconfirm --onefile --windowed --icon "logo.ico" --add-data "logo.ico;." --name "HyperMove" "main.py"


🤝 Contributing & Support

If you love this tool and it saved you hours of transfer time, consider supporting the project!
Found a bug or want to request a feature? Feel free to open an Issue or submit a Pull Request.
