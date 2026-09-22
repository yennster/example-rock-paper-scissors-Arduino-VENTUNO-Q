# Rock Paper Scissors TTC 2026 — Arduino VENTUNO Q

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
arduino-app-cli app list           # confirm the app id
arduino-app-cli app start user:rock-paper-scissors-game
```

> After editing the app you must copy it to the board again (Step 1) and
> restart it — App Lab runs its own copy under `/home/arduino/ArduinoApps/`,
> so local edits are not picked up until they are transferred.

Once successfully started, navigate to `http://<device-ip>:7000` in your browser and start playing!

<img width="1024" alt="Playing Rock Paper Scissors against the Arduino UNO Q" src="https://github.com/user-attachments/assets/27faa88b-0311-47c7-9fba-0d31438e45b4" />


Good luck!


### Game flow

The match is **continuous** — there is nothing to lock in. Press start once and rounds
keep coming until you pause.

1. Press **Start Match**. A 3-2-1 countdown runs for each round.
2. Show your hand gesture (rock, paper, or scissors) to the camera. You can keep changing
   it right up to the last instant.
3. Your gesture is read **at the moment the countdown hits zero** ("shoot!"), and the
   Arduino reveals its random move.
4. The result is held on screen for a moment, then the next countdown starts automatically.
5. **Pause** stops the loop after the current round; **Reset** clears the scores, history
   and commentary.

While all of this happens, the **Live Camera** panel shows the feed straight from the
model runner with the detected bounding boxes drawn on top, plus a transparent coloured
wash and emoji for whatever class is currently predicted — so you can see exactly what
the model sees.

## Configuration

All settings are in [python/main.py](python/main.py) at the top. Each one can also be
overridden with an environment variable of the same name.

| Setting | Default | Description |
|---------|---------|-------------|
| `CONFIDENCE` | `0.4` | Minimum confidence to accept a detection (`CONFIDENCE_THRESHOLD`) |
| `COUNTDOWN_SECS` | `3` | Countdown duration before the gesture is read |
| `RESULT_HOLD_SECS` | `3.5` | How long the result stays on screen before the next round |
| `COMMENTARY_MIN_INTERVAL` | `8` | Minimum seconds between LLM commentary lines |
| `DEBUG_DETECTIONS` | unset | Set to `1` to log every raw detection payload |


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

**The Live Camera panel stays black / "Waiting for the camera feed…":**
- Look for `[CAMERA] Live preview stream active` in the logs. If you instead see
  `[CAMERA] No preview frames yet from the model runner`, the brick is running but the
  model runner has not sent a preview frame yet — give it a few seconds after start-up.
- If the logs say `no camera preview support`, the installed `video_object_detection`
  brick predates the `camera_preview` option. Update Arduino App Lab; the game still
  works, just without the live feed.
- The feed is served by the app itself at `/camera` (MJPEG) on the same port as the UI.

**`error gathering device information while adding custom device "/dev/fastrpc-cdsp"`:**

This is a board-level failure, not an app bug — the app never gets to start.

On the UNO Q the object detection brick runs the **QNN** (Hexagon DSP) model runner, and
its compose file requires the `/dev/fastrpc-cdsp` device node. That node only exists when
the CDSP remote processor has booted successfully. The CDSP is known to **intermittently
fail to come up at boot** (see [qualcomm-linux/kernel#1086](https://github.com/qualcomm-linux/kernel/issues/1086));
when it does, every `/dev/fastrpc-cdsp*` node is missing and Docker refuses to create the
container. This is why the app can start after one boot and fail after the next.

Diagnose it over SSH on the board:

```bash
ls -l /dev/fastrpc*                       # cdsp node present at all?
for r in /sys/class/remoteproc/remoteproc*; do echo "$r $(cat $r/name) $(cat $r/state)"; done
dmesg | grep -iE 'fastrpc|remoteproc|cdsp|q6v5'
```

A failed CDSP bring-up looks like `start timed out` followed by
`remoteproc remoteprocN: can't start rproc cdsp: -110`, and `/dev/fastrpc-adsp` will
usually still be present while `/dev/fastrpc-cdsp` is not.

Recovery, in order of least effort:

1. **Reboot the board.** Because the failure is intermittent, the next boot usually
   brings the CDSP up. Confirm with `ls -l /dev/fastrpc*` before starting the app.
2. **Restart the CDSP remoteproc in place** (substitute the index whose `name` is `cdsp`):

   ```bash
   sudo sh -c 'echo stop  > /sys/class/remoteproc/remoteprocN/state'
   sudo sh -c 'echo start > /sys/class/remoteproc/remoteprocN/state'
   ls -l /dev/fastrpc*
   ```

3. Once the node is back, start the app again — no changes to the app are needed.

If the CDSP never comes up on any boot, the Hexagon firmware may be missing; check
`dmesg` for remoteproc firmware-load errors and for the presence of the DSP images that
the brick mounts from `/usr/share/qcom`.

**"App runner: no" in logs:**
- The `App` class couldn't be imported. Make sure you're running via `arduino-app-cli app start`, not `python3 main.py` directly

**Model not found:**
- Verify the `.eim` file exists at the path in `app.yaml`
- Ensure the file is executable: `chmod +x /home/arduino/.arduino-bricks/ei-models/rcp-model.eim`

Feel free to reach out to us on the [Edge Impulse forum](https://forum.edgeimpulse.com) or the [Edge Impulse Discord server](https://discord.gg/edgeimpulse) if you need help.



## Disclaimer

This project is intended for educational and experimental purposes only. It is not hardened for production use. Do not deploy in any safety-critical environments without proper security, testing, and validation.
