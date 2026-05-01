**📖 What is HyperMove?**

HyperMove Pro is an elite, graphical utility designed specifically for moving massive amounts of data—like 150GB+ games, 4K/8K raw video files, and heavy backups—at the absolute physical limit of your SSDs and HDDs.

Standard operating systems copy files by loading them into your RAM first. For massive files, this fills your memory, slows down your PC, and creates points of failure. HyperMove bypasses the OS entirely using Direct I/O, piping data straight from drive to drive while wrapping the experience in a breathtaking, hardware-accelerated fluid UI.

✨ Key Features

- 🚀 Direct I/O Hardware Bypass: Features a tuned 16MB chunk pipeline to saturate Gen4 and Gen5 NVMe bandwidth without touching your system's RAM cache.

+ 🛡️ Bulletproof Resumption: Built-in hardware `fsync` flushing. If you lose power during a massive transfer, HyperMove safely auto-resumes byte-for-byte.

- 🌊 Liquid Telemetry Dashboard: Monitor your exact transfer speeds in real-time with a lag-free, GPU-accelerated fluid wave graph.

- 🔒 Data Integrity Verification: Optional deep-scan verification ensures that every single bit on your target drive perfectly matches the source.

- 📊 CSV Auditing: Automatically generate professional `.csv` log files for every transfer session.

- 🎨 Native OS Glass UI: Features authentic background blur (Acrylic/Mica), spring-physics drop zones, and dynamic themes (Cyan for Copy, Magenta for Move).

📥 How to Download & Run

You don't need to install any code to run this. It operates as a fully standalone portable executable.

1. Go to the [Releases page](https://github.com/Apologiesm/HyperMove/releases) of this repository.

2. Download the latest `HyperMove.exe` file for Windows.

3. Double-click the `.exe` to launch the application instantly. No installation required!

🖥️ How to Use

1. Launch the App: Open `HyperMove.exe`.

2. Select Source: Drag and drop your massive game folder or video files into the top Source drop zone.

3. Select Destination: Drag and drop your target NVMe/HDD into the bottom Destination drop zone.

4. Configure: * Choose Copy (keeps original files) or Move (wipes original files safely after a verified transfer).

- Set your Hardware Profile (Select Direct I/O for maximum NVMe speeds).

5. Start: Click START ENGINE, sit back, and watch the Liquid Telemetry Graph max out your drive.

🛠️ For Developers (Build from Source)

If you want to run the raw Python code or compile the executable yourself:

	# 1. Clone the repository
	git clone [https://github.com/yourusername/HyperMove.git](https://github.com/yourusername/HyperMove.git)
	
	# 2. Navigate to the directory
	cd HyperMove
	
	# 3. Install required dependencies
	pip install PySide6 pyinstaller pynput
	
	# 4. Run the application directly
	python main.py
	
	# 5. Build the standalone executable
	pyinstaller --noconfirm --onefile --windowed --icon "logo.ico" --add-data "logo.ico;." --name "HyperMove" "main.py"


🤝 Support & Feedback

If this tool saved you hours of waiting on Windows file transfers, consider sharing it! Found a bug or have a feature request? Feel free to open an Issue or submit a Pull Request.
