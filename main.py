import argparse
import datasets
import numpy as np
import models
import torch
import time
from torch.autograd import Variable
import os
import pickle

def accuracy(data, model, no_class = None, on_cuda=False):
    acc = 0.
    total = 0.

    for mini in data:

        inputs = Variable(mini['sample'], requires_grad=False).float()
        targets = Variable(mini['labels'], requires_grad=False).float()

        if on_cuda:
            inputs = inputs.cuda()
            targets = targets.cuda()

        max_index_target = targets.max(dim=1)[1].data.cpu().long().numpy()
        max_index_pred = model(inputs).max(dim=1)[1].data.cpu().long().numpy()

        id_to_keep = np.ones_like(max_index_target)
        if no_class is not None:
            id_to_keep = max_index_target == no_class

        acc += ((max_index_target == max_index_pred) * id_to_keep).sum()
        total += sum(id_to_keep)

    acc = acc / float(total)
    return acc

def get_most_important_gene(data, model):

    for mini in data:
        inputs = Variable(mini['sample'], requires_grad=False).float().cuda()

        max_index_pred = model(inputs).max(dim=1)[1].data.cpu().long()


def accuracy_per_class(data, model, nb_class, idx_to_str, on_cuda=False):

    acc = {}

    all_target = None
    all_pred = None

    # Get the predictions
    for mini in data:

        inputs = Variable(mini['sample'], requires_grad=False).float()
        targets = Variable(mini['labels'], requires_grad=False).float()

        if on_cuda:
            inputs = inputs.cuda()
            targets = targets.cuda()


        max_index_target = targets.max(dim=1)[1].data.cpu().long().numpy()
        max_index_pred = model(inputs).max(dim=1)[1].data.cpu().long().numpy()

        if all_target is None:
            all_target = max_index_target
        else:
            all_target = np.concatenate([all_target, max_index_target])

        if all_pred is None:
            all_pred = max_index_pred
        else:
            all_pred = np.concatenate([all_pred, max_index_pred])

    # Get the class specific
    for cl in range(nb_class):

        id_to_keep = all_target == cl

        tmp = ((all_target == all_pred) * id_to_keep).sum()
        total = sum(id_to_keep)
        acc[idx_to_str(cl)] = tmp / float(total)

    return acc



def build_parser():
    parser = argparse.ArgumentParser(
        description="Model for convolution-graph network (CGN)")

    parser.add_argument('--epoch', default=10, type=int, help='The number of epochs we want ot train the network.')
    parser.add_argument('--seed', default=1993, type=int, help='Seed for random initialization and stuff.')
    parser.add_argument('--batch-size', default=100, type=int, help="The batch size.")
    parser.add_argument('--tensorboard', default='./testing123/', help='The folder where to store the experiments. Will be created if not already exists.')
    parser.add_argument('--lr', default=1e-3, type=float, help='learning rate')
    parser.add_argument('--weight-decay', default=0., type=float, help='weight decay (L2 loss).')
    parser.add_argument('--l1-loss', default=0., type=float, help='L1 loss.')
    parser.add_argument('--momentum', default=0.9, type=float, help='momentum')
    parser.add_argument('--data-dir', default='/data/milatmp1/dutilfra/transcriptome/graph/', help='The folder contening the dataset.')
    parser.add_argument('--dataset', choices=['random', 'tcga-tissue', 'tcga-brca'], default='random', help='Which dataset to use.')
    parser.add_argument('--scale-free', action='store_true', help='If we want a scale-free random adjacency matrix for the dataset.')
    parser.add_argument('--cuda', action='store_true', help='If we want to run on gpu.')
    parser.add_argument('--sparse', action='store_true', help='If we want to use sparse matrix implementation.')
    parser.add_argument('--not-norm-adj', action='store_true', help="If we don't want to normalize the adjancy matrix.")
    parser.add_argument('--make-it-work-for-Joseph', action='store_true', help="Don't store anything in tensorboard, otherwise a segfault can happen.")
    parser.add_argument('--name', type=str, default=None, help="If we want to add a random str to the folder.")

    # Model specific options
    parser.add_argument('--num-channel', default=32, type=int, help='Number of channel in the CGN.')
    parser.add_argument('--model', default='cgn', choices=['cgn', 'mlp', 'lcg'], help='Number of channel in the CGN.')
    parser.add_argument('--num-layer', default=1, type=int, help='Number of convolution layer in the CGN.')
    parser.add_argument('--nb-class', default=None, type=int, help="Number of class for the dataset (won't work with random graph).")
    parser.add_argument('--nb-examples', default=None, type=int, help="Number of samples to train on.")
    parser.add_argument('--nb-per-class', default=None, type=int, help="Number of samples per class.")
    parser.add_argument('--train-ratio', default=0.8, type=float, help="The ratio of data to be used in the training set.")

    return parser

def parse_args(argv):

    if type(argv) == list or argv is None:
        opt = build_parser().parse_args(argv)
    else:
        opt = argv

    return opt

def main(argv=None):

    opt = parse_args(argv)

    batch_size = opt.batch_size
    epoch = opt.epoch
    seed = opt.seed
    learning_rate = opt.lr
    weight_decay = opt.weight_decay
    momentum = opt.momentum
    num_channel = opt.num_channel
    num_layer = opt.num_layer
    sparse = opt.sparse
    on_cuda = opt.cuda
    tensorboard = opt.tensorboard
    nb_class = opt.nb_class
    not_norm_adj = opt.not_norm_adj
    nb_examples = opt.nb_examples
    nb_per_class = opt.nb_per_class
    train_ratio = opt.train_ratio
    l1_loss = opt.l1_loss
    model = opt.model

    # Dataset
    dataset_name = opt.dataset
    scale_free = opt.scale_free

    # The experiment unique id.
    param = vars(opt).copy()
    del param['data_dir']
    del param['tensorboard']
    del param['cuda']
    del param['sparse']
    del param['make_it_work_for_Joseph']
    v_to_delete = []
    for v in param:
        if param[v] is None:
            v_to_delete.append(v)
    for v in v_to_delete:
        del param[v]

    exp_name = '_'.join(['{}={}'.format(k, v) for k, v, in param.iteritems()])
    print vars(opt)

    # seed
    if on_cuda:
        torch.cuda.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
    else:
        torch.manual_seed(seed)
        #torch.manual_seed_all(seed)

    # creating the dataset
    print "Getting the dataset..."

    if dataset_name == 'random':

        print "Getting a random graph"
        transform_adj_func = None if not_norm_adj else datasets.ApprNormalizeLaplacian()
        nb_samples = 10000 if nb_examples is None else nb_examples

        # TODO: add parametrisation of the fake dataset, or would it polute everything?
        dataset = datasets.RandomGraphDataset(nb_nodes=1000, nb_edges=2000, nb_examples=nb_samples,
                                          transform_adj_func=transform_adj_func, scale_free=scale_free, seed=seed)
        nb_class = 2 # Right now we only have 2 class

    elif dataset_name == 'tcga-tissue':

        print "Getting TCGA tissue type"
        compute_path = None if scale_free else '/data/milatmp1/dutilfra/transcriptome/graph/tcga_tissue_ApprNormalizeLaplacian.npy'
        transform_adj_func = None if not_norm_adj or num_layer == 0 or model != 'cgn' else datasets.ApprNormalizeLaplacian(compute_path)

        # To have a feel of TCGA, take a look at 'view_graph_TCGA.ipynb'
        dataset = datasets.TCGATissue(transform_adj_func=transform_adj_func, # To delete
            nb_class=nb_class, use_random_adj=scale_free)

        if nb_class is None: # means we keep all the class (29 I think)
            nb_class = len(dict(dataset.labels.attrs))/2

    elif dataset_name == 'tcga-brca':

        print "Getting TCGA BRCA type"
        compute_path = None if scale_free else '/data/milatmp1/dutilfra/transcriptome/graph/tcga_brca_ApprNormalizeLaplacian.npy'
        transform_adj_func = None if not_norm_adj or num_layer == 0 or model != 'cgn' else datasets.ApprNormalizeLaplacian(compute_path)

        # To have a feel of TCGA, take a look at 'view_graph_TCGA.ipynb'
        dataset = datasets.BRCACoexpr(transform_adj_func=transform_adj_func, # To delete
            nb_class=nb_class, use_random_adj=scale_free)

        if nb_class is None: # means we keep all the class (29 I think)
            nb_class = len(dict(dataset.labels.attrs))/2

    else:
        raise ValueError

    print "Nb of edges = ", dataset.nb_edges


    # dataset loader
    train_set, valid_set, test_set = datasets.split_dataset(dataset, batch_size=batch_size, seed=seed,
                                                            nb_samples=nb_examples, train_ratio=train_ratio, nb_per_class=nb_per_class)

    # Creating a model
    # To have a feel of the model, please take a look at cgn.ipynb
    print "Getting the model..."
    my_model = None
    if model == 'cgn':
        my_model = models.CGN(dataset.nb_nodes, 1, [num_channel] * num_layer, dataset.get_adj(), nb_class,
                     on_cuda=on_cuda, to_dense=sparse)
    elif model == 'mlp':
        my_model = models.MLP(dataset.nb_nodes, [num_channel] * num_layer, nb_class,
                     on_cuda=on_cuda)
    elif model == 'lcg':
        my_model = models.LCG(dataset.nb_nodes, dataset.get_adj(), out_dim=nb_class,
                              on_cuda=on_cuda, channels=num_channel, num_layers=num_layer)
    else:
        print "unknown model"

    print "Our model:"
    print my_model

    # Train the cgn
    criterion = torch.nn.MultiLabelSoftMarginLoss(size_average=True)
    optimizer = torch.optim.SGD(my_model.parameters(), lr=learning_rate, momentum=momentum, weight_decay=weight_decay)

    if on_cuda:
        print "Putting the model on gpu..."
        my_model.cuda()

    # For tensorboard
    writer = None
    if not opt.make_it_work_for_Joseph:
        from logger import Logger

        if not os.path.exists(tensorboard):
            os.mkdir(tensorboard)

        exp_dir = os.path.join(tensorboard, exp_name)
        if not os.path.exists(exp_dir):
            os.mkdir(exp_dir)

        # dumping the options
        pickle.dump(opt, open(os.path.join(exp_dir, 'options.pkl'), 'wb'))
        writer = Logger(exp_dir)
        print "We will log everything in ", exp_dir
    else:
        print "Nothing will be log, everything will only be shown on screen."

    for t in range(epoch):

        start_timer = time.time()

        for no_b, mini in enumerate(train_set):

            inputs, targets = mini['sample'], mini['labels']

            inputs = Variable(inputs, requires_grad=False).float()
            targets = Variable(targets, requires_grad=False).float()

            if on_cuda:
                inputs = inputs.cuda()
                targets = targets.cuda()

            # Forward pass: Compute predicted y by passing x to the model
            y_pred = my_model(inputs).float()

            # Compute and print loss
            loss = criterion(y_pred, targets)

            if epoch == 1:
                print "Done minibatch {}".format(no_b)
                print(t, loss.data[0])

            # Zero gradients, perform a backward pass, and update the weights.
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

        # Add some metric for tensorboard
        # Loss
        if writer is not None:
            writer.scalar_summary('loss', loss[0].data.cpu().numpy(), t) # TODO pretty sure there is a bug here.

        # time
        time_this_epoch = time.time() - start_timer

        if writer is not None:
            writer.scalar_summary('time', time_this_epoch, t)

        # accuracy, for all the sets
        acc = {}
        for my_set, set_name in zip([train_set, valid_set, test_set], ['train', 'valid']):#, 'test']):
            acc[set_name] = accuracy(my_set, my_model, on_cuda=on_cuda)

            if writer is not None:
                writer.scalar_summary('accuracy_{}'.format(set_name), acc[set_name], t)

            # accuracy for a different class
            acc_per_class = accuracy_per_class(my_set, my_model, nb_class, lambda x: dataset.labels_name(x), on_cuda=on_cuda)

            if writer is not None:
                for k, v in acc_per_class.iteritems():
                    writer.scalar_summary('accuracy_{}/{}'.format(set_name, k), v, t)

        # small summary.
        print "epoch {}, loss: {:.03f}, acc train: {:0.2f} acc valid: {:0.2f}, time: {:.02f} sec".format(t,
                                                                                                         loss.data[0],
                                                                                                         acc['train'],
                                                                                                         acc['valid'],
                                                                                                         time_this_epoch)

    print "Done!"

if __name__ == '__main__':

    main()
