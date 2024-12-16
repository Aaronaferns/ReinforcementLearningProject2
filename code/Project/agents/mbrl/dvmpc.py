from agents.dynamics.dynamics_model import *
import numpy as np
from base import *
from agents.nets.value_network import *
import datetime
import time
from agents.dynamics.dfnn import *
from agents.opt.cem import *
from agents.utils import *
from torch.optim import Adam
import torch as th
import torch.nn as nn


class DVPMCAgent(BaseAgent):
    def __init__(
            self,
            env,
            num_agents,
            model=fwDiffNNModel, #dynamics model
            value_model=DeepValueNetwork, #Value network model
            sample_policy=None,
            m_buffer_size=10000, #Memory buffer size for the dynamics model
            v_buffer_size=400000, #Replay buffer size
            min_fit_data=500,
            steps_p_fit=500,
            train_on_done=True, # Ignore the steps and train after every episode
            epochs_p_fit=5,
            gamma=0.99,
            alpha=7e-5,
            val_grad_clip=3.0,
            decay=False,# 0.99, # Decay rate per episode
            batch_size=512,
            rollout_length=10,
            replan_period=1,
            shots_p_step=150,
            model_arch=[32,32,32,32],
            model_lr=5e-5,
            init_data=None,
            action_sampler=CEM,
            ):
        super(DVPMCAgent, self).__init__(env)

        self._model = model(self._nS, self._nA, data_size=m_buffer_size, hidden_units=model_arch, lr=model_lr)
        self._best_model = model(self._nS, self._nA, data_size=m_buffer_size, hidden_units=model_arch, lr=model_lr)
        self._best_avg_model = model(self._nS, self._nA, data_size=m_buffer_size, hidden_units=model_arch, lr=model_lr)

        self._action_sampler = action_sampler(self._nA, rollout_length, shots_p_step, self._min, self._max, self.evaluate_action_traj)
        current_time = datetime.now().strftime("%Y%m%d-%H%M%S")

        #self.sts_done_fn = env.sts_done_fn
        self.device = ('cuda:3' if th.cuda.is_available() else 'cpu')
        self._gamma = gamma
        self._val_lr = alpha
       
        self._val_grad_norm = val_grad_clip
        self._decay = decay
        
        self._value_model = value_model(self._nS).to(self.device)
        self._val_opt = Adam(params = self._value_model.parameters(), lr=alpha)
        print(self._value_model)
        self._best_value_model = value_model(self._nS)
        self._best_avg_value_model = value_model(self._nS)
        self._buffer = ReplayBuffer(self._nS, self._nA, buffer_capacity=v_buffer_size)
        self._batch_size = batch_size

        self._min_fit_data = min_fit_data
        self._steps_p_fit=steps_p_fit
        self._train_on_done = train_on_done
        self._epochs_p_fit = epochs_p_fit

        self._rollout_len = rollout_length
        self._replan_period = replan_period
        self._step_count = 0
        self._shots_p_step = shots_p_step
        self.loss_fn = nn.MSELoss()
        self._acts = []
        self._pred_traj = []

        self._train_step_count = 0
        self._trained = False
        self._trained_since_check = False
        self.succ = 0
        self.fails = 0

    def reset(self):
        self._acts = []
        self._pred_traj = []
        self._step_count = 0

    def sample_action(self, state):
        # TODO: Test value
        if not self._trained:
            return self._random_act_sample(1)[0,:]

        state = th.tensor(state).squeeze()
        if len(self._acts) == 0 or self._step_count >= self._replan_period:
            self._acts = self._action_sampler.get_sol(state)
            self._step_count = 0


        self._step_count += 1

        act, self._acts = self._acts[0,:], self._acts[1:,:]

        return act

    def noiseless_sample_action(self, state):
        pred_traj = None
        state = th.tensor(state).squeeze()
        elapsed_t = 0.0
        if len(self._acts) == 0 or self._step_count >= self._replan_period:
            start = time.time()
            self._acts = self._action_sampler.get_sol(state)
            end = time.time()
            elapsed_t = end - start

            self._pred_traj = None#self.state_rollout(np.array([state]), self._acts[0,:])
            self._step_count = 0

        self._step_count += 1

        act, self._acts = self._acts[0,:], self._acts[1:,:]
        return act, self._pred_traj, elapsed_t

    def state_rollout(self, state, action_traj):
        s_batch = np.squeeze(np.copy(state))

        state_trajs = np.copy(state)
        for i in range(action_traj.shape[0]):
            acts = action_traj[i,:]
            pred_inp = np.expand_dims(np.concatenate([s_batch, acts], axis=0), axis=0)
            s_batch = np.squeeze(self._model.predict(pred_inp.to(self._model.device)))

            state_trajs = np.vstack([state_trajs, np.expand_dims(s_batch, axis=0)])

        return state_trajs


    def evaluate_action_traj(self, init_state, act_trajs, return_states=False):
        init_state = th.tensor(init_state, dtype=th.float32).unsqueeze(0)
        act_trajs = th.tensor(act_trajs, dtype=th.float32) 
        
        # s_batch = tf.tile(init_state, (self._shots_p_step,1))
        s_batch = init_state.repeat(self._shots_p_step, 1)

        # state_trajs = tf.tile(init_state, (self._shots_p_step,1))
        state_trajs = init_state.repeat(self._shots_p_step, 1)

        # rew_trajs = np.array([]).reshape(0, self._shots_p_step)

        #Rollout simulation
        for i in range(self._rollout_len):
            acts = act_trajs[:,i,:]
            #  pred_inp = tf.concat([s_batch, acts], axis=1)
            pred_inp = th.cat([s_batch, acts], dim=1)
            #  s_batch = tf.squeeze(self._model.predict(pred_inp))
            s_batch = self._model.predict(pred_inp.to(self._model.device)).squeeze()
            # state_trajs = tf.concat([state_trajs, s_batch], axis=1)
            state_trajs = th.cat([state_trajs, s_batch], dim=1)

        # state_trajs = tf.reshape(state_trajs, (self._shots_p_step,-1,self._num_obs))
        state_trajs = state_trajs.view(self._shots_p_step, -1, self._nS)
        last_vals = self._evaluate_traj_rews(state_trajs, act_trajs)

        return (last_vals, state_trajs) if return_states else last_vals

    def _evaluate_traj_rews(self, state_batch, act_batch):
        rew_batch = None
        state_batch = state_batch.to(self.device)
        val = self._value_model(state_batch[:,0,:])
        
        for i in range(1, state_batch.shape[1]):
            discount = self._gamma ** i
            val += discount * self._value_model(state_batch[:,i,:])# * (1 - self.done_fn(state_batch[:,i,:])
        return val.to("cpu")

    def _random_act_sample(self, num_samples):
        acts = np.random.uniform(self._min, self._max, size=(num_samples, self._nA))
        return acts


    def _update_val(
        self, state_batch, reward_batch, next_state_batch, not_done_batch, step):  
        reward_batch = reward_batch.to(self.device)
        next_state_batch = next_state_batch.to(self.device)
        not_done_batch = not_done_batch.to(self.device)   
        with th.no_grad():
            y = reward_batch + self._gamma * self._value_model(next_state_batch.to(self.device)) * not_done_batch
        state_batch = state_batch.to(self.device)
        est_val = self._value_model(state_batch)
        val_loss = self.loss_fn(y ,est_val)

        self._val_opt.zero_grad()
        val_loss.backward()

        # (Optional) Clip gradients if necessary
        if self._val_grad_norm is not None:
            th.nn.utils.clip_grad_norm_(self._value_model.parameters(), self._val_grad_norm)

        # Apply gradients
        self._val_opt.step()

        # Return value loss and gradients for inspection
        val_grad = [param.grad.clone() for param in self._value_model.parameters()]
        return val_loss, val_grad

    def train_step(self, state, action, reward, next_state, done):
        self._model.push_data(np.squeeze(state), action, np.squeeze(next_state))
        state = th.tensor(state)
        next_state = th.tensor(next_state)
        self._train_step_count += 1
        hist = None
        if self._train_on_done:
            if done:# and self._train_step_count < 100:
                self._trained = True
                self._train_step_count += 1
                hist = self._model.train(num_epochs=self._epochs_p_fit)


        elif (self._model.data_count >= self._min_fit_data) \
           and (self._train_step_count >= self._steps_p_fit):
            self._trained = True
            self._train_step_count = 0
            hist = self._model.train(num_epochs=self._epochs_p_fit)

        if done and self._decay:
            self._val_opt.learning_rate = self._decay*self._val_opt.learning_rate

        # action = action[0]
        state = state.squeeze().float()
        # Generate the internal reward for the lower level network
        next_state = next_state.squeeze().float()
        reward = reward
        # done = self.sts_done_fn(state.unsqueeze(0), action.unsqueeze(0), next_state.unsqueeze(0))
        self._buffer.add((state, action, reward, next_state, done))
        done = done
        #1.0 if (abs(next_state[0]) > 2.4 or abs(next_state[2]) > 2*np.pi * 12/360) else 0.0
        if done:
            s = next_state
            a = np.zeros(self._nA)
            ns = np.zeros(self._nS)
            r = reward
            self._buffer.add((s, a, r, ns, done))
            
        state_batch, _, rew_batch, nstate_batch, done_batch = self._buffer.sample_batch(self._batch_size)
        db = th.where(done_batch == 0.0, th.tensor(1.0), th.tensor(0.0))

        val_loss, grad = self._update_val(state_batch, rew_batch, nstate_batch, db, self._train_step_count)

        return hist, val_loss

    @property
    def trained_since_last_check(self):
        trained = self._trained_since_check
        self._trained_since_check = False
        return trained

    def push_val_data(self, curr_state, act, next_state, rew=None):
        # act = act[0]
        state = th.tensor(curr_state).squeeze().float()
        next_state = th.tensor(next_state).squeeze().float()
        self._model.push_val_data(curr_state, act, next_state, rew)

    def set_best(self):
        self._best_model.set_model_to(self._model)
        self._best_value_model.load_state_dict(self._value_model.state_dict())

    def set_best_avg(self):
        self._best_avg_model.set_model_to(self._model)
        self._best_avg_value_model.load_state_dict(self._value_model.state_dict())

    # Save all of our networks
    def save_models(self, save_dir, save_type):
        if save_type == 'final':
            self._model.save_model(save_dir,save_type)
            os.makedirs(os.path.join(save_dir,"/val"), exist_ok=True)
            th.save(self._value_model.state_dict(), os.path.join(save_dir,f"/val/value_model.pth"))
        elif save_type == 'best':
            self._best_model.save_model(save_dir,save_type)
            os.makedirs(os.path.join(save_dir,"/val"), exist_ok=True)
            th.save(self._best_value_model.state_dict(), os.path.join(save_dir , f"/val/value_model.pth"))
    
        elif save_type == 'best_avg':
            self._best_avg_model.save_model(save_dir,save_type)
            os.makedirs(os.path.join(save_dir,"/val"), exist_ok=True)
            th.save(self._best_avg_value_model.state_dict(), os.path.join(save_dir ,f"/val/value_model.pth"))
      
  
    # Load all of the networks
    def load_models(self, save_dir):
        self._model.load_model(save_dir)
        model_path = os.path.join(save_dir,"/val/value_model.pth")
        if os.path.exists(model_path):
            self._value_model.load_state_dict(th.load(model_path))
            print(f"Model loaded from {model_path}")
        else:
            raise FileNotFoundError(f"No model found at {model_path}")
        self._trained = True
