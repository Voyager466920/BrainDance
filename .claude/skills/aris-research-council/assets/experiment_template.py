"""Synthetic CPU classification pilot; not a VLA study or paper reproduction."""
import csv
import json
import math
import os
from pathlib import Path
import random

if os.environ.get('BRAINDANCE_DEVICE') != 'cpu':
    raise RuntimeError('This smoke-test template requires a CPU execution target.')

seed = 17
rng = random.Random(seed)

def samples(count):
    rows = []
    for _ in range(count):
        y = rng.randrange(2)
        rows.append(([rng.gauss(1.0 if y else -1.0, 1.0),
                      rng.gauss(0.7 if y else -0.7, 1.0)], y))
    return rows

train, test = samples(512), samples(256)
weights = [0.0, 0.0, 0.0]
history = []
for epoch in range(100):
    gradient = [0.0, 0.0, 0.0]
    loss = 0.0
    for x, y in train:
        z = weights[0]*x[0] + weights[1]*x[1] + weights[2]
        probability = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))
        error = probability - y
        for i, value in enumerate([*x, 1.0]):
            gradient[i] += error*value
        loss -= y*math.log(max(probability, 1e-12)) + (1-y)*math.log(max(1-probability, 1e-12))
    weights = [w-0.2*g/len(train) for w, g in zip(weights, gradient)]
    history.append({'epoch': epoch+1, 'training_loss': loss/len(train)})
    if epoch % 25 == 0:
        print(json.dumps(history[-1]), flush=True)

baseline_label = int(sum(y for _, y in train) >= len(train)/2)
predictions = [int(weights[0]*x[0]+weights[1]*x[1]+weights[2] >= 0) for x, _ in test]
baseline = sum(y == baseline_label for _, y in test)/len(test)
accuracy = sum(pred == y for pred, (_, y) in zip(predictions, test))/len(test)
metrics = {'dataset': 'synthetic Gaussian binary classification', 'seed': seed,
           'train_samples': len(train), 'test_samples': len(test),
           'baseline': {'accuracy': baseline}, 'candidate': {'accuracy': accuracy},
           'limitation': 'One synthetic pilot, not statistical or real-world validation.'}
Path(os.environ['BRAINDANCE_METRICS_PATH']).write_text(json.dumps(metrics, indent=2))
artifacts = Path(os.environ['BRAINDANCE_ARTIFACT_DIR'])
(artifacts/'training_curve.json').write_text(json.dumps(history, indent=2))
with (artifacts/'predictions.csv').open('w', newline='') as stream:
    writer = csv.writer(stream)
    writer.writerow(['x1', 'x2', 'label', 'prediction'])
    for (x, y), prediction in zip(test, predictions):
        writer.writerow([*x, y, prediction])
print(json.dumps(metrics), flush=True)
