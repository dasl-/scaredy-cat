# steps to install https://github.com/ageitgey/face_recognition
# some modifications from https://gist.github.com/ageitgey/1ac8dbe8572f3f533df6269dab35df65
# changed libatlas-dev -> libatlas-base-dev

sudo apt-get update
sudo apt-get upgrade
sudo apt-get install build-essential \
    cmake \
    gfortran \
    git \
    wget \
    curl \
    graphicsmagick \
    libgraphicsmagick1-dev \
    libatlas-base-dev \
    libavcodec-dev \
    libavformat-dev \
    libboost-all-dev \
    libgtk2.0-dev \
    libjpeg-dev \
    liblapack-dev \
    libswscale-dev \
    pkg-config \
    python3-dev \
    python3-numpy \
    python3-pip \
    zip
sudo apt-get clean

sudo apt-get install python3-picamera2

# skipped this step bc i couldnt figure out the picamera2 incantation
# sudo pip3 install --upgrade picamera[array]

sudo nano /etc/dphys-swapfile

< change CONF_SWAPSIZE=100 to CONF_SWAPSIZE=1024 and save / exit nano >

sudo /etc/init.d/dphys-swapfile restart

mkdir -p dlib

# the instructions said to clone a different branch ( git clone -b 'v19.6' --single-branch https://github.com/davisking/dlib.git dlib/ ).
# I had to clone a more recent version to solve "AttributeError: 'Thread' object has no attribute 'isAlive'" encoubntered during the
# subsequent installation step (see: https://github.com/jupyter-vim/jupyter-vim/issues/51 )
git clone -b 'v19.24' --single-branch https://github.com/davisking/dlib.git dlib/
cd ./dlib

# next step takes ~40 minutes on rpi 4
sudo python3 setup.py install --compiler-flags "-mfpu=neon"

sudo pip3 install face_recognition

sudo nano /etc/dphys-swapfile

< change CONF_SWAPSIZE=1024 to CONF_SWAPSIZE=100 and save / exit nano >

sudo /etc/init.d/dphys-swapfile restart

git clone https://github.com/ageitgey/face_recognition.git

https://github.com/raspberrypi/picamera2#installation  - enable viewing preview images over ssh
sudo apt install -y python3-pyqt5 python3-opengl


# test code (separate). Opencv installation takes a while. Currently installing in tmux session and logging installation output to ~/opencvinstall.log
UPDATE: this test code is bullshit and doesn't work. Skip it next time.
sudo pip3 install imutils opencv-python

curl https://raw.githubusercontent.com/kipr/opencv/master/data/haarcascades/haarcascade_frontalface_default.xml > haarcascade_frontalface_default.xml

test script: https://gist.github.com/dasl-/6fb8dc0997d51b4c44e9ef60b116e097
