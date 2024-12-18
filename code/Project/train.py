import argparse
from arg_lists import *
from scripts.utils import *
from scripts.graphing import *
import gymnasium as gym
import matplotlib.pyplot as plt

parser = argparse.ArgumentParser(description='This script handles running learning \
        algorithms for various environments and agent types.')

parser.add_argument('--agent', dest='agent', metavar='agent_name', default='DVPMC',
        help='Name of the agent type we want to train. Valid agents: ' + str(agent_list))

parser.add_argument('--env', dest='env', metavar='env_name', default='pendulum',
        help='Name of the environment we want to train on. Valid environments: ' + str(env_list))

parser.add_argument('--eps', dest='eps', metavar='num_eps', type=int, default=500,
        help='The number of episodes to train for.')

parser.add_argument('--rand-reset', dest='true_rand', default='',
        help='Whether to implement a true random reset. Anything but \'\' means True.')

parser.add_argument('--ts-save', dest='ts_save', default='',
        help='Whether to timestamp the agent save after running or not. Anything but \'\' means True.')

parser.add_argument('--load-name', dest='load_name', metavar='agent_load_name', default='',
        help='A folder ID for the saved model we want to load. Most of the path is auto-generated in the format \
                ~/agents/saved/<ENV NAME>/<AGENT NAME>/<LOAD_NAME>')

parser.add_argument('--save-results', dest='save_res', default='y',
        help='Whether to save the training results after running or not. Anything but \'\' means True. Directory is autogenerated with a timestamp.')

args = parser.parse_args()

agent = None
env = None
num_eps = args.eps
agent_path = None

if args.env not in env_dict.keys():
    print(str(args.env) + " is not a valid environment. Please choose from the list: " + str(env_dict.keys()))
    exit(-1)


env = gym.make(env_dict[args.env])

if args.agent not in agent_dict.keys():
    print(str(args.agent) + " is not a valid agent. Please choose from: " + str(agent_dict.keys()))
    exit(-1)

runner = agent_dict[args.agent](env)

print('Running learning for {} steps with agent {} in env {}'.format(args.eps, args.agent, args.env))


rew, info = runner.train(num_eps)



# Assuming you've already populated the lists with data
# Plotting the training loss and validation loss
plt.figure(figsize=(12, 6))

# Plot Training Loss
plt.subplot(1, 2, 1)
plt.plot(runner._full_dyn_model_hist['tloss'], label='Training Loss', color='blue')
plt.xlabel('steps')
plt.ylabel('Loss')
plt.title('Training Loss Dynamic Model')
plt.legend()

# Plot Validation Loss
plt.subplot(1, 2, 2)
plt.plot(runner._full_dyn_model_hist['vloss'], label='Validation Loss', color='red')
plt.xlabel('steps')
plt.ylabel('Loss')
plt.title('Validation Loss Dynamic Model')
plt.legend()

plt.tight_layout()
plt.savefig('results/plots/dynamics_model_losses.png', dpi=300)
plt.close()



plt.figure(figsize=(6, 6))
plt.plot(runner._full_val_model_hist, label='Value Model History', color='green')
plt.xlabel('epochs')
plt.ylabel('Metric Value')
plt.title('Value Model Loss')
plt.legend()
plt.savefig('results/plots/value_model_history.png', dpi=300)
plt.close()

save_path = ''
if args.save_res:
    save_path = generate_results_dir(args.env, args.agent, suffix='train')
    runner.dump_agent_attrs(save_path)
    save_data(save_path + 'train_data', rew)
    save_data(save_path + 'train_info', info)
    #save_data(save_path + 'info', info)

plot_rewards(rew, save_dir=save_path)

