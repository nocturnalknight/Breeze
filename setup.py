import setuptools

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setuptools.setup(
    name="breeze_connect",
    version="1.0.58",
    author="ICICI Direct Breeze",
    author_email="breezeapi@icicisecurities.com",
    description="ICICI Direct Breeze",
    long_description=long_description,
    long_description_content_type="text/markdown",
    install_requires=['python-socketio[client]','requests','pandas'],
    extras_require={
        "trading_app": [
            "fastapi>=0.115.0",
            "jinja2>=3.1.0",
            "uvicorn>=0.30.0",
        ],
    },
    url="https://github.com/Idirect-Tech/Breeze-Python-SDK/",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    packages=setuptools.find_packages(),
    package_data={
        "trading_app": ["templates/*.html", "static/*.css", "static/*.js"],
    },
    python_requires=">=3.6",
)
