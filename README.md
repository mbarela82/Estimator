# **Cabinet Estimator Setup and Build Guide**

This guide provides step-by-step instructions to set up the necessary Python environment, install dependencies, and package the Cabinet Estimator application into a standalone executable (.exe) for Windows.

## **Prerequisites**

- **Python 3:** Ensure you have Python 3 installed on your system. You can download it from [python.org](https://www.python.org/downloads/). During installation, make sure to check the box that says **"Add Python to PATH"**.

## **Part 1: Setting Up the Development Environment**

Follow these steps to get the application running from the source code.

### **Step 1: Prepare Your Project Folder**

Create a folder for your project and place the following files inside it:

- app.py (The main application script)
- CTkToolTip.py (The tooltip helper script)
- door_icon.ico (The application icon file)
- requirements.txt (Included in this response)

### **Step 2: Create a Virtual Environment**

Open a Command Prompt or PowerShell, navigate into your project folder, and run the following command to create a virtual environment named venv:

```
python \-m venv venv
```

_This creates a venv folder that will contain all the project's specific libraries, keeping them separate from your computer's main Python installation._

### **Step 3: Activate the Virtual Environment**

You must activate the environment before installing libraries or running the app. The command differs based on your operating system.

- **On Windows (Command Prompt/PowerShell):**

```
.\venv\Scripts\activate
```

- **On macOS/Linux:**

```
source venv/bin/activate
```

After activation, you will see (venv) at the beginning of your command prompt line.

### **Step 4: Install Required Libraries**

With your virtual environment active, install all the necessary libraries using the requirements.txt file with this single command:

```
pip install \-r requirements.txt
```

### **Step 5: Run the Application**

You can now run the application directly from your development environment:

```
python app.py
```

The application window should appear, and it will create a CC-Estimator folder in your user's home directory to store the database.

## **Part 2: Building the Executable (.exe)**

Follow these steps to package the application into a single executable file that can be distributed and run on other Windows computers without needing Python installed.

### **Step 1: Install PyInstaller**

If you followed Part 1, PyInstaller is already installed. If not, make sure your virtual environment is active and run:

```
pip install pyinstaller
```

### **Step 2: Run the Build Command**

While inside your project folder with the virtual environment active, run the following command in your terminal. This command tells PyInstaller how to bundle your application.

```
pyinstaller \--name "CabinetEstimator" \--onefile \--windowed \--icon="door\_icon.ico" \--add-data "door\_icon.ico;." \--hidden-import="fitz.fitz" app.py
```

**Command Breakdown:**

- \--name "CabinetEstimator": Sets the final name of your executable.
- \--onefile: Packages everything into a single .exe file.
- \--windowed: Prevents a black console window from appearing when the app runs.
- \--icon="door_icon.ico": Sets the icon for the executable file itself.
- \--add-data "door_icon.ico;.": **Crucially**, this bundles the icon file inside the .exe so the application can use it for its window icon at runtime.
- \--hidden-import="fitz.fitz": Ensures the PDF library (PyMuPDF) is included correctly.
- app.py: Your main application script.

The build process may take a few minutes.

### **Step 3: Locate and Run Your Executable**

Once finished, you will find two new folders: build and dist.  
Your standalone application is inside the **dist** folder, named **CabinetEstimator.exe**.  
You can now share this single .exe file. When run on a new computer, it will automatically create the CC-Estimator folder in the user's home directory to store its database.
