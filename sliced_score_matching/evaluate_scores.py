import torch
import torch.autograd as autograd
import numpy as np
import os
import torchvision.transforms as transforms
from torchvision.datasets import MNIST, CIFAR10
from torch.utils.data import DataLoader, Subset
from models.nice_approxbp import Logit, approx_backprop_score_matching, NICE
from losses.score_matching import exact_score_matching
from tqdm import tqdm

# 计算fisher的那个最直接的
def compute_scores(energy_net, samples, train=False, use_hessian=False):
    samples.requires_grad_(True)
    if use_hessian:
        scores = torch.zeros(samples.shape[0], device=samples.device)
        for i in tqdm.tqdm(range(samples.shape[1])):
            logp = -energy_net(samples).sum() # 这个负号+
            grad1 = autograd.grad(logp, samples, create_graph=True)[0]
            grad = autograd.grad(grad1[:, i].sum(), samples)[0][:, i]
            scores += grad.detach()
    else:
        logp = -energy_net(samples).sum()
        grad1 = autograd.grad(logp, samples, create_graph=True)[0]
        scores = (torch.norm(grad1, dim=-1) ** 2).detach()
    return scores

# 遍历数据集（验证集和测试集）
def evaluate_scores(flow, val_loader, test_loader, device, noise_sigma=0.0):
    def energy_net(inputs):
        energy, _ = flow(inputs, inv=False)
        return -energy
    
    print("Evaluating on validation set!")
    val_scores = []
    for i, (X, y) in enumerate(val_loader):
        flattened_X = X.type(torch.float32).to(device).view(X.shape[0], -1)
        if noise_sigma is not None:
            flattened_X += torch.randn_like(flattened_X) * noise_sigma
        scores = compute_scores(energy_net, flattened_X, train=False)
        val_scores.append(scores)
    val_scores = torch.cat(val_scores)

    print("Evaluating on test set!")
    test_scores = []
    for i, (X, y) in enumerate(test_loader):
        flattened_X = X.type(torch.float32).to(device).view(X.shape[0], -1)
        if noise_sigma is not None:
            flattened_X += torch.randn_like(flattened_X) * noise_sigma
        scores = compute_scores(energy_net, flattened_X, train=False)
        test_scores.append(scores)
    test_scores = torch.cat(test_scores)
    
    return val_scores, test_scores

# 没被调用过
def evaluate_model(flow, val_loader, test_loader, device, noise_sigma = 0.0):
    def energy_net(inputs):
        energy, _ = flow(inputs, inv=False)
        return -energy
    print("Evaluating on validation set!")
    val_logps = []
    val_sm_losses = []
    results = {}

    for i, (X, y) in enumerate(val_loader):
        flattened_X = X.type(torch.float32).to(device).view(X.shape[0], -1)
        if noise_sigma is not None:
            flattened_X += torch.randn_like(flattened_X) * noise_sigma

        logp = -energy_net(flattened_X)
        logp = logp.mean()
        val_logps.append(logp)
        sm_loss = exact_score_matching(energy_net, flattened_X, train=False).mean()
        val_sm_losses.append(sm_loss)

    val_logp = sum(val_logps) / len(val_logps)
    val_sm_loss = sum(val_sm_losses) / len(val_sm_losses)
    results['val_logp'] = val_logp.detach().cpu().numpy().item()
    results['val_sm_loss'] = val_sm_loss.detach().cpu().numpy().item()
    print("Val logp: {}, score matching loss: {}".format(val_logp.item(), val_sm_loss.item()))

    print("Evaluating on test set!")
    test_logps = []
    test_sm_losses = []

    for i, (X, y) in enumerate(test_loader):
        flattened_X = X.type(torch.float32).to(device).view(X.shape[0], -1)
        if noise_sigma is not None:
            flattened_X += torch.randn_like(flattened_X) * noise_sigma

        logp = -energy_net(flattened_X)
        logp = logp.mean()
        test_logps.append(logp)
        sm_loss = exact_score_matching(energy_net, flattened_X, train=False).mean()
        test_sm_losses.append(sm_loss)

    test_logp = sum(test_logps) / len(test_logps)
    test_sm_loss = sum(test_sm_losses) / len(test_sm_losses)
    results['test_logp'] =test_logp.detach().cpu().numpy().item()
    results['test_sm_loss'] =test_sm_loss.detach().cpu().numpy().item()
    print("Test logp: {}, score matching loss: {}".format(test_logp.item(), test_sm_loss.item()))
    
sigma = 0.1
#  数据集路径
cifar10_route = '/cpfs01/projects-SSD/cfff-448d03a18a24_SSD/drj_22210240082/drj/DATASET/images/cifar10/'
mnist_route = '/cpfs01/projects-SSD/cfff-448d03a18a24_SSD/drj_22210240082/drj/DATASET/images/mnist/'

for dataset_name in ["MNIST", "CIFAR10"]:
# for dataset_name in ["CIFAR10"]:
    d = 784 if dataset_name == 'MNIST' else 3072 # input dim 32*32*3 for CIFAR10
    # 数据集处理
    if dataset_name == 'CIFAR10':
        transform = transforms.Compose([
            transforms.Resize(32),
            transforms.ToTensor()
        ])
        dataset = CIFAR10(cifar10_route, train=True, download=True,
                            transform=transform)
        test_dataset = CIFAR10(cifar10_route, train=False, download=True,
                                transform=transform)
    elif dataset_name == 'MNIST':
        transform = transforms.Compose([
            transforms.Resize(28),
            transforms.ToTensor()
        ])
        dataset = MNIST(mnist_route, train=True, download=True,
                        transform=transform)
        test_dataset = MNIST(mnist_route, train=False, download=True,
                                transform=transform)
    
    num_items = len(dataset)
    indices = list(range(num_items))
    random_state = np.random.get_state()
    np.random.seed(2019)
    np.random.shuffle(indices)
    np.random.set_state(random_state)
    train_indices, val_indices = indices[:int(num_items * 0.9)], indices[int(num_items * 0.9):]
    val_dataset = Subset(dataset, val_indices)
    dataset = Subset(dataset, train_indices)

    dataloader = DataLoader(dataset, batch_size=128, shuffle=True, num_workers=2)
    val_loader = DataLoader(val_dataset, batch_size=128, shuffle=True, num_workers=2)
    test_loader = DataLoader(test_dataset, batch_size=128, shuffle=True, num_workers=2)

    device = torch.device('cuda')

    # matching 模型
    flow = NICE(d, 1000, 5).to(device)
    if dataset_name == "MNIST":
        state_dict = torch.load('run/results/mnist_sigma_{}/best_on_esm_nice.pth'.format(sigma))
    else: # cifar10 
        state_dict = torch.load('run/results/cifar_sigma_{}/best_on_esm_nice.pth'.format(sigma))
    flow.load_state_dict(state_dict)

    val_scores, test_scores = evaluate_scores(flow, val_loader, test_loader, device, noise_sigma=sigma)
    # test score是计算在所有数据集上的平均
    # 先平均再求迹等于先求迹再平均
    print("%s: dFIL (prior) = %.2f" % (dataset_name, test_scores.mean() / d)) 