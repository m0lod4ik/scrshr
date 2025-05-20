from cx_Freeze import setup, Executable

setup(
    name="myapp",
    version="1.0",
    description="My Python App",
    executables=[Executable("server.py")]
)