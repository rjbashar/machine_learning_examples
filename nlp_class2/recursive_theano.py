import sys
import numpy as np
import matplotlib.pyplot as plt
import theano
import theano.tensor as T

from sklearn.utils import shuffle
from util import init_weight, get_ptb_data, display_tree
from datetime import datetime


class RecursiveNN:
    def __init__(self, V, D, K):
        self.V = V
        self.D = D
        self.K = K

    def fit(self, trees, learning_rate=10e-4, mu=0.99, reg=10e-3, epochs=15, activation=T.nnet.relu, train_inner_nodes=False):
        D = self.D
        V = self.V
        K = self.K
        self.f = activation
        N = len(trees)

        We = init_weight(V, D)
        Wh = np.random.randn(2, D, D) / np.sqrt(2 + D + D)
        bh = np.zeros(D)
        Wo = init_weight(D, K)
        bo = np.zeros(K)

        self.We = theano.shared(We)
        self.Wh = theano.shared(Wh)
        self.bh = theano.shared(bh)
        self.Wo = theano.shared(Wo)
        self.bo = theano.shared(bo)
        self.params = [self.We, self.Wh, self.bh, self.Wo, self.bo]

        words = T.ivector('words')
        parents = T.ivector('parents')
        relations = T.ivector('relations')
        labels = T.ivector('labels')

        def recurrence(n, hiddens, words, parents, relations):
            w = words[n]
            # any non-word will have index -1
            # if T.ge(w, 0):
            #     hiddens = T.set_subtensor(hiddens[n], self.We[w])
            # else:
            #     hiddens = T.set_subtensor(hiddens[n], self.f(hiddens[n] + self.bh))
            hiddens = T.switch(
                T.ge(w, 0),
                T.set_subtensor(hiddens[n], self.We[w]),
                T.set_subtensor(hiddens[n], self.f(hiddens[n] + self.bh))
            )

            r = relations[n]
            p = parents[n]
            if T.ge(p, 0):
                # root will have parent -1
                hiddens = T.set_subtensor(hiddens[p], hiddens[p] + hiddens[n].dot(self.Wh[r]))
            return hiddens

        hiddens = T.zeros((words.shape[0], D))

        h, _ = theano.scan(
            fn=recurrence,
            outputs_info=[hiddens],
            n_steps=words.shape[0],
            sequences=T.arange(words.shape[0]),
            non_sequences=[words, parents, relations],
        )

        py_x = T.nnet.softmax(h[:,0,:].dot(self.Wo) + self.bo)

        prediction = T.argmax(py_x, axis=1)
        
        rcost = T.sum([(p*p).mean() for p in self.params])
        if train_inner_nodes:
            cost = -T.mean(T.log(py_x[T.arange(labels.shape[0]), labels])) + rcost
        else:
            cost = -T.mean(T.log(py_x[-1, labels[-1]])) + rcost
        grads = T.grad(cost, self.params)
        dparams = [theano.shared(p.get_value()*0) for p in self.params]

        updates = [
            (p, p + mu*dp - learning_rate*g) for p, dp, g in zip(self.params, dparams, grads)
        ] + [
            (dp, mu*dp - learning_rate*g) for dp, g in zip(dparams, grads)
        ]

        self.cost_predict_op = theano.function(
            inputs=[words, parents, relations, labels],
            outputs=[cost, prediction],
            allow_input_downcast=True,
        )

        self.train_op = theano.function(
            inputs=[words, parents, relations, labels],
            outputs=[cost, prediction],
            updates=updates
        )

        costs = []
        sequence_indexes = range(N)
        if train_inner_nodes:
            n_total = sum(len(words) for words, _, _, _ in trees)
        else:
            n_total = N
        for i in xrange(epochs):
            t0 = datetime.now()
            sequence_indexes = shuffle(sequence_indexes)
            n_correct = 0
            cost = 0
            it = 0
            for j in sequence_indexes:
                words, par, rel, lab = trees[j]
                c, p = self.train_op(words, par, rel, lab)
                if np.isnan(c):
                    print "Cost is nan! Let's stop here. Why don't you try decreasing the learning rate?"
                    exit()
                cost += c
                if train_inner_nodes:
                    n_correct += np.sum(p == lab)
                else:
                    n_correct += (p[-1] == lab[-1])
                it += 1
                if it % 1 == 0:
                    sys.stdout.write("j/N: %d/%d correct rate so far: %f, cost so far: %f\r" % (it, N, float(n_correct)/n_total, cost))
                    sys.stdout.flush()
            print "i:", i, "cost:", cost, "correct rate:", (float(n_correct)/n_total), "time for epoch:", (datetime.now() - t0)
            costs.append(cost)

        plt.plot(costs)
        plt.show()

    def score(self, trees):
        n_total = len(trees)
        n_correct = 0
        for words, par, rel, lab in trees:
            _, p = self.cost_predict_op(words, par, rel, lab)
            n_correct += (p[-1] == lab[-1])
        return float(n_correct) / n_total


def add_idx_to_tree(tree, current_idx):
    # post-order labeling of tree nodes
    if tree is None:
        return current_idx
    current_idx = add_idx_to_tree(tree.left, current_idx)
    current_idx = add_idx_to_tree(tree.right, current_idx)
    tree.idx = current_idx
    current_idx += 1
    return current_idx


def tree2list(tree, parent_idx, is_left=False, is_right=False):
    if tree is None:
        return [], [], [], []

    w = tree.word if tree.word is not None else -1
    if is_left:
        r = 0
    elif is_right:
        r = 1
    else:
        r = -1
    words_left, parents_left, relations_left, labels_left = tree2list(tree.left, tree.idx, is_left=True)
    words_right, parents_right, relations_right, labels_right = tree2list(tree.right, tree.idx, is_right=True)

    words = words_left + words_right + [w]
    parents = parents_left + parents_right + [parent_idx]
    relations = relations_left + relations_right + [r]
    labels = labels_left + labels_right + [tree.label]

    return words, parents, relations, labels


def main():
    train, test, word2idx = get_ptb_data()

    for t in train:
        add_idx_to_tree(t, 0)
    train = [tree2list(t, -1) for t in train]

    for t in test:
        add_idx_to_tree(t, 0)
    test = [tree2list(t, -1) for t in test]

    # train = train[:1000]
    # test = test[:100]

    V = len(word2idx)
    print "vocab size:", V
    D = 80
    K = 5

    model = RecursiveNN(V, D, K)
    model.fit(train, activation=T.nnet.relu)
    print "train accuracy:", model.score(train)
    print "test accuracy:", model.score(test)


if __name__ == '__main__':
    main()
