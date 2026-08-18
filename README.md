# Rock Paper Scissors Game with Arduino VENTUNO Q

A real-time Rock-Paper-Scissors game running on the Arduino UNO Q using an Edge Impulse object detection model.

<img width="1024" alt="Playing agains the Arduino VENTUNO Q" src="https://github.com/user-attachments/assets/e9828e20-6a0e-41b7-a675-73f105d712e0" />

The camera detects your hand gesture (rock, paper, or scissors) via object detection inference, while the Arduino picks a random move, and the local LLM comments the game. Are you going to win the Arduino?


## Deployment

### Prerequisites

- Arduino VENTUNO Q with Arduino App Lab
- USB camera connected to the board
- [Edge Impulse](https://edgeimpulse.com/) machine learning model trained to detect `rock`, `paper`, and `scissors` as you can find in this public project [here](https://studio.edgeimpulse.com/public/903134/live). Clone it and re-train it to improve the accuracy with your light and background.

### Step 1: Transfer the app

Clone [this repository](https://github.com/mpous/example-rock-paper-scissors-Arduino-VENTUNO-Q) to your local machine.

Or `Download as a ZIP file` from the Github repository.

Copy the entire `Rock Paper Scissors` folder to the Arduino UNO Q board:

```bash
scp -r Rock-Paper-Scissors-Arduino-VENTUNO-Q/ arduino@<device-ip>:/home/arduino/ArduinoApps/RPS-game
```

or use the Arduino App Lab `Create new App` button in the `My Apps` section and import the ZIP file.

![Create new app](assets/img/arduino-app-lab-create-new-app.png)


### Step 2: Deploy the Object Detection model

Get into the `Rock Paper Scissor` app into the Arduino App Lab.

Click in the Brick `Video Object Detection` and then click `Train new AI model` in the bottom.

![Train new AI model](assets/img/bricks-ai-models.png)

Log In into your Arduino account and the Edge Impulse account and then train your own `Rock Paper Scissors` model or clone [this public project](https://studio.edgeimpulse.com/public/903134/live) and re-train it.

![Edge Impulse Studio project](assets/img/edge-impulse-project.png)

![Add new images into the Training dataset](assets/img/add-new-images.png)

![Create the Impulse](assets/img/create-the-impulse.png)

![Train the model](assets/img/train-the-model.png)

Go to deploy the model as `Arduino VENTUNO Q` or as `Linux AARCH64 with Qualcomm QNN`.

![Deploy the model as Arduino UNO Q or Linux aarch64](assets/img/edge-impulse-project.png)

Then the deployed models will appear in the brick of the Arduino App Lab when you will go to the `AI models` tab. Select the `Rock paper scissors` model.


### Step 2.1: Deploy the local LLM

Select the brick `Large Language Model LLM` and then go to the tab `AI models`.

<img width="1024" alt="Install LLM Gemma 3 1B to the application" src="https://github.com/user-attachments/assets/b1a42a5d-bdaf-4aed-b7ef-f2cdfc201d32" />

Download the model that you would like to have. In this case, I downloaded the `Gemma 3 1B` and it works well.

And check that it's being added in the `app.yaml` file of the app.

<img width="1024" alt="app.yaml file with the models deployed" src="https://github.com/user-attachments/assets/0c7e02ff-d97a-4980-91a1-811cc7ac6bdb" />


### Step 3: Start the app

Click on the `Rock Paper Scissors` application and then click `Run`.

Alternatively, via SSH you can start the application using the Arduino App Lab CLI.

```bash
arduino-app-cli app start user:rock-paper-scissors-game
```

Once successfully started, navigate to `http://<device-ip>:7000` in your browser and start playing!

<img width="1024" alt="Playing Rock Paper Scissors against the Arduino UNO Q" src="https://github.com/user-attachments/assets/27faa88b-0311-47c7-9fba-0d31438e45b4" />


Good luck!


### Game flow

1. Show your hand gesture (rock, paper, or scissors) to the camera.
2. The detection panel on the left shows what the model sees in real-time after running inference on a local object detection Edge Impulse model.
3. Click **Play Round** — your gesture is **locked in** at that moment.
4. The Arduino reveals its random move and the winner is shown



## Configuration

All settings are in [python/main.py](python/main.py) at the top:

| Setting | Default | Description |
|---------|---------|-------------|
| `CONFIDENCE_THRESHOLD` | `0.6` | Minimum confidence to accept a detection |
| `COUNTDOWN_SECS` | `3` | Countdown duration before evaluating |
| `RESULT_HOLD_SECS` | `3` | How long the result stays on screen |


### Improving the model

In case that you want to create your own object detection model using [Edge Impulse](https://edgeimp.com/edgeai).

Collect data, label it and train the neural network. Test it in Edge Impulse and when you will feel confident, deploy it as an Arduino UNO Q model or Linux aarch64.

Then follow the same instructions that you performed to add it to the app's brick.


## Become an Edge Impulse expert

Want to learn more about how Edge Impulse ork? Try one of the [Edge Impulse courses](https://www.edgeimpulse.com/blog/introduction-to-edge-ai-course/).


## Troubleshooting

**"No gesture detected" every round:**
- Check that the brick is initialized: look for `[BRICK] VideoObjectDetection initialized` in logs
- Check that `App.run()` is active: look for `[MODE] App runner: yes` in logs
- Look for `[BRICK-RAW]` lines — if absent, the brick callback isn't firing
- Ensure your model labels match `rock`, `paper`, `scissors` (lowercase)

**"App runner: no" in logs:**
- The `App` class couldn't be imported. Make sure you're running via `arduino-app-cli app start`, not `python3 main.py` directly

**Model not found:**
- Verify the `.eim` file exists at the path in `app.yaml`
- Ensure the file is executable: `chmod +x /home/arduino/.arduino-bricks/ei-models/rcp-model.eim`

Feel free to reach out to us on the [Edge Impulse forum](https://forum.edgeimpulse.com) or the [Edge Impulse Discord server](https://discord.gg/edgeimpulse) if you need help.



## Disclaimer

This project is intended for educational and experimental purposes only. It is not hardened for production use. Do not deploy in any safety-critical environments without proper security, testing, and validation.
