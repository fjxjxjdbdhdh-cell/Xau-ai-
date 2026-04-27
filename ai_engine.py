import pickle, os, numpy as np, logging

logger = logging.getLogger(__name__)

class AIPredictor:
    def __init__(self, path="model.pkl"):
        self.path = path
        self.model = None
        if os.path.exists(path):
            try:
                with open(path, "rb") as f:
                    self.model = pickle.load(f)
            except:
                pass

    def predict_proba(self, features):
        if self.model is None:
            return 0.5
        try:
            return self.model.predict_proba([features])[0][1]
        except:
            return 0.5

    def save(self):
        if self.model:
            with open(self.path, "wb") as f:
                pickle.dump(self.model, f)
